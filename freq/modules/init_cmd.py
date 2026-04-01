"""FREQ init — first-run setup wizard.

10-phase deployment pipeline:
1. Welcome + prerequisites check
2. Cluster configuration (PVE nodes, gateway, nameserver → freq.toml)
3. Service account creation (configurable, NOPASSWD sudo)
4. SSH key generation
5. PVE node deployment (create account + deploy key on each node)
6. PDM setup (detect/install Proxmox Datacenter Manager, configure remote)
7. Fleet host deployment (create account + deploy key on each host)
8. Admin account setup (RBAC roles)
9. Configuration + verification
10. Summary

Must run as root. Creates a service account (default: from freq.toml) with
NOPASSWD sudo on this host and all managed nodes.

"the genesis. everything starts here." — freq init
"""
import base64
import datetime
import getpass
import os
import re
import shutil
import subprocess
import tempfile
import time

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import PLATFORM_SSH


# Device types that support per-device credentials
# Legacy list — will be replaced by deployer registry categories
DEVICE_HTYPES = ("pfsense", "idrac", "switch", "truenas")

INIT_MARKER = None  # Set in cmd_init from cfg

# ── Constants ────────────────────────────────────────────────────────────

# Timeouts (seconds)
DEFAULT_CMD_TIMEOUT = 30
SSH_CONNECT_TIMEOUT = 5
IDRAC_SETUP_TIMEOUT = 60
IDRAC_VERIFY_TIMEOUT = 15
SWITCH_CONFIG_TIMEOUT = 30
QUICK_CHECK_TIMEOUT = 10
PING_TIMEOUT = 5
VERIFY_TIMEOUT = 20

# iDRAC user slot range (slots 1-2 are reserved by Dell for root/admin)
IDRAC_SLOT_MIN = 3
IDRAC_SLOT_MAX = 17  # exclusive — range(3, 17) gives slots 3-16

# IOS SSH key line width (PEM line wrapping limit)
IOS_KEY_LINE_WIDTH = 72

# Error markers in remote deployment scripts
MARKER_DEPLOY_OK = "DEPLOY_OK"
MARKER_SETUP_OK = "SETUP_OK"
MARKER_USERADD_FAIL = "USERADD_FAIL"
MARKER_CHPASSWD_FAIL = "CHPASSWD_FAIL"
MARKER_CLEAN_OK = "CLEAN_OK"

# Input validation patterns
_VALID_USERNAME = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
_VALID_LABEL = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')


def _validate_username(name):
    """Validate a Linux username. Returns True if valid."""
    return bool(_VALID_USERNAME.match(name))


def _validate_label(label):
    """Validate a host label. Returns True if valid."""
    return bool(_VALID_LABEL.match(label))


def _gen_idrac_slot_check():
    """Generate the racadm command to query all iDRAC user slots."""
    return "; ".join(
        f"echo SLOT{i}=$(racadm get iDRAC.Users.{i}.UserName 2>/dev/null | grep -oP '(?<=UserName=).*')"
        for i in range(IDRAC_SLOT_MIN, IDRAC_SLOT_MAX)
    )


def _parse_idrac_slots(output, svc_name):
    """Parse iDRAC slot query output. Returns (target_slot, existing_slot).

    target_slot: first empty slot found (or None)
    existing_slot: slot where svc_name already exists (or None)
    """
    target_slot = None
    existing_slot = None
    for i in range(IDRAC_SLOT_MIN, IDRAC_SLOT_MAX):
        marker = f"SLOT{i}="
        for line in output.split("\n"):
            if marker in line:
                val = line.split(marker, 1)[1].strip()
                if val == svc_name:
                    existing_slot = i
                    break
                elif not val and target_slot is None:
                    target_slot = i
    return target_slot, existing_slot


def _run(cmd, timeout=DEFAULT_CMD_TIMEOUT):
    """Run a command, return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)


def _run_with_input(cmd, input_text, timeout=DEFAULT_CMD_TIMEOUT):
    """Run a command with stdin input, return (rc, stdout, stderr).

    Used for IOS switch config — commands must be piped via stdin,
    not passed as SSH exec arguments.
    """
    try:
        r = subprocess.run(cmd, input=input_text, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)


def _load_device_credentials(cred_file):
    """Load per-device-type credentials from a TOML file.

    Supports three section name formats (in priority order):
        [firewall:pfsense]    — new category:vendor format
        [firewall]            — category fallback (applies to all vendors in category)
        [pfsense]             — legacy htype format (backward compat)

    Returns dict keyed by LEGACY htype for backward compat with fleet deploy:
        {"pfsense": {"user": "root", "password": "thepass"}, ...}
    """
    from freq.deployers import HTYPE_COMPAT

    result = {}
    if not cred_file or not os.path.isfile(cred_file):
        return result

    # Parse TOML
    try:
        if tomllib is not None:
            with open(cred_file, "rb") as f:
                data = tomllib.load(f)
        else:
            # Minimal fallback: read key=value pairs per section
            data = {}
            section = None
            for line in open(cred_file):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                    data[section] = {}
                elif "=" in line and section:
                    k, v = line.split("=", 1)
                    data[section][k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        fmt.step_warn(f"Failed to parse device credentials: {e}")
        return result

    def _read_entry(entry, label):
        """Extract user + password from a credential entry."""
        user = entry.get("user", "root")
        pw_file = entry.get("password_file", "")
        if not pw_file:
            fmt.step_warn(f"Device '{label}' has no password_file — skipped")
            return None
        try:
            with open(pw_file) as f:
                password = f.read().strip()
        except (OSError, IOError) as e:
            fmt.step_warn(f"Cannot read {label} password from {pw_file}: {e}")
            return None
        return {"user": user, "password": password}

    # Build lookup: check all three formats per device type
    for legacy_htype, (category, vendor) in HTYPE_COMPAT.items():
        # Skip server types — they don't use device credentials
        if category == "server":
            continue

        # Priority: category:vendor > category > legacy htype
        entry = None
        cv_key = f"{category}:{vendor}"
        if cv_key in data:
            entry = data[cv_key]
        elif category in data and isinstance(data[category], dict) and "user" in data.get(category, {}):
            entry = data[category]
        elif legacy_htype in data:
            entry = data[legacy_htype]

        if entry:
            cred = _read_entry(entry, cv_key)
            if cred:
                result[legacy_htype] = cred

    return result


def _read_password(prompt="Password"):
    """Read password twice, confirm match. Returns password or None."""
    border = f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}"
    try:
        p1 = getpass.getpass(f"{border}  {prompt}: ")
        p2 = getpass.getpass(f"{border}  Confirm {prompt.lower()}: ")
        if p1 != p2:
            fmt.step_fail("Passwords do not match")
            return None
        if len(p1) < 4:
            fmt.step_fail("Password too short (min 4 characters)")
            return None
        return p1
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _input(prompt, default=""):
    """Read input with optional default (left-bordered for box continuity)."""
    suffix = f" [{default}]" if default else ""
    border = f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}"
    try:
        val = input(f"{border}  {prompt}{suffix}: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def _confirm(prompt, default=False):
    """Yes/no confirmation (left-bordered for box continuity)."""
    suffix = "[Y/n]" if default else "[y/N]"
    border = f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}"
    try:
        ans = input(f"{border}  {prompt} {suffix}: ").strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _phase(num, total, title):
    """Print phase header."""
    fmt.blank()
    fmt.divider(f"Phase {num}/{total}: {title}")
    fmt.blank()


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════════════════════════════

def cmd_init(cfg: FreqConfig, pack, args) -> int:
    """First-run setup wizard for FREQ."""
    from freq.core.personality import splash

    global INIT_MARKER
    INIT_MARKER = os.path.join(cfg.conf_dir, ".initialized")

    # Parse flags
    check_mode = getattr(args, "check", False)
    reset_mode = getattr(args, "reset", False)
    dry_run = getattr(args, "dry_run", False)
    uninstall_mode = getattr(args, "uninstall", False)

    # --check: validation with remote host verification (no root needed)
    if check_mode:
        return _init_check(cfg)

    # --fix: scan fleet, find broken hosts, redeploy
    fix_mode = getattr(args, "fix", False)
    if fix_mode:
        return _init_fix(cfg, args)

    # --uninstall [--dry-run]: remove FREQ from all hosts
    if uninstall_mode:
        if dry_run:
            return _uninstall_dry_run(cfg)
        headless = getattr(args, "headless", False)
        if headless:
            return _uninstall_headless(cfg)
        return _uninstall_interactive(cfg)

    # --dry-run (no root needed)
    if dry_run:
        return _init_dry_run(cfg)

    # --headless: non-interactive mode (agent-driven deployment)
    headless = getattr(args, "headless", False)
    if headless:
        return _init_headless(cfg, args)

    # Must be root for actual init
    if os.geteuid() != 0:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}freq init must be run as root.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Needed for: account creation, sudoers, SSH key permissions{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run: sudo freq init{fmt.C.RESET}")
        fmt.blank()
        return 1

    # --reset: wipe and start fresh
    if reset_mode:
        return _init_reset(cfg)

    # Splash
    splash(pack, cfg.version)
    print()
    fmt.header("Init — First-Run Setup")
    fmt.blank()

    # Check if already initialized
    yes_flag = getattr(args, "yes", False)
    if os.path.isfile(INIT_MARKER):
        with open(INIT_MARKER) as f:
            ver = f.read().strip()
        fmt.line(f"  {fmt.C.GREEN}FREQ already initialized ({ver}){fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run 'freq doctor' to check status, or re-run below.{fmt.C.RESET}")
        fmt.blank()
        if not yes_flag and not _confirm("Re-run initialization wizard?"):
            return 0

    # State passed between phases
    ctx = {
        "svc_name": cfg.ssh_service_account,
        "svc_pass": "",
        "key_path": "",
        "pubkey": "",
        "rsa_key_path": "",
        "rsa_pubkey": "",
    }

    total = 10

    # Phase 1: Welcome + Prerequisites
    _phase(1, total, "Welcome + Prerequisites")
    if not _phase_welcome(cfg):
        return 1

    # Phase 2: Cluster Configuration
    _phase(2, total, "Cluster Configuration")
    _phase_configure(cfg, args)

    # Phase 3: Service Account
    _phase(3, total, "Service Account Setup")
    if not _phase_service_account(cfg, ctx, args):
        return 1

    # Phase 4: SSH Keys
    _phase(4, total, "SSH Key Generation")
    _phase_ssh_keys(cfg, ctx)

    # Phase 5: PVE Node Deployment
    _phase(5, total, "PVE Node Deployment")
    _phase_pve_deploy(cfg, ctx, args)

    # Phase 6: PDM Setup
    _phase(6, total, "PDM Setup")
    _phase_pdm(cfg, ctx, args)

    # Phase 7: Fleet Host Deployment
    _phase(7, total, "Fleet Host Deployment")
    _phase_fleet_deploy(cfg, ctx, args)

    # Phase 8: Admin Accounts
    _phase(8, total, "Admin Account Setup")
    _phase_admin_setup(cfg, ctx)

    # Phase 9: Verification
    _phase(9, total, "Configuration + Verification")
    verified = _phase_verify(cfg, ctx)

    # Phase 10: Summary
    _phase(10, total, "Summary")
    _phase_summary(cfg, ctx, verified, pack)

    logger.info("init complete", service_account=ctx["svc_name"])
    return 0 if verified else 1


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: Welcome + Prerequisites
# ═══════════════════════════════════════════════════════════════════

def _phase_welcome(cfg):
    """Check prerequisites are installed."""
    fmt.line(f"  {fmt.C.DIM}Checking prerequisites...{fmt.C.RESET}")
    fmt.blank()

    prereqs = {
        "ssh": "SSH client (required)",
        "ssh-keygen": "SSH key generation (required)",
        "openssl": "Encryption — vault (required)",
    }
    optional = {
        "sshpass": "Password-based SSH (for initial deployment)",
        "jq": "JSON parsing (optional)",
        "curl": "HTTP requests (optional)",
    }

    ok = True
    for cmd, desc in prereqs.items():
        rc, _, _ = _run(["which", cmd])
        if rc == 0:
            fmt.step_ok(desc)
        else:
            fmt.step_fail(f"{desc} — '{cmd}' not found")
            ok = False

    for cmd, desc in optional.items():
        rc, _, _ = _run(["which", cmd])
        if rc == 0:
            fmt.step_ok(desc)
        elif cmd == "sshpass":
            # Auto-install sshpass — detect package manager and try sudo install
            pkg_managers = [
                ("apt-get", ["sudo", "apt-get", "install", "-y", "sshpass"]),
                ("dnf", ["sudo", "dnf", "install", "-y", "sshpass"]),
                ("zypper", ["sudo", "zypper", "--non-interactive", "install", "sshpass"]),
            ]
            found_pm = False
            for pkg_mgr, install_args in pkg_managers:
                pm_rc, _, _ = _run(["which", pkg_mgr])
                if pm_rc == 0:
                    found_pm = True
                    fmt.step_start(f"Installing sshpass via {pkg_mgr}...")
                    inst_rc, _, _ = _run(install_args, timeout=120)
                    if inst_rc == 0:
                        fmt.step_ok(f"{desc} (auto-installed)")
                    else:
                        fmt.step_warn(f"{desc} — auto-install failed (install manually)")
                    break
            if not found_pm:
                fmt.step_warn(f"{desc} — '{cmd}' not found (install recommended)")
        else:
            fmt.step_warn(f"{desc} — '{cmd}' not found (install recommended)")

    if not ok:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}Missing required dependencies. Install them and re-run.{fmt.C.RESET}")
        return False

    # Create data directories
    fmt.blank()
    fmt.step_start("Creating data directories")
    dirs = [cfg.data_dir, cfg.vault_dir, cfg.key_dir,
            os.path.dirname(cfg.log_file)]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    fmt.step_ok(f"Data directories ready ({len(dirs)} created)")

    # Seed config files from .example templates
    _seed_config_files(cfg)

    return True


def _seed_config_files(cfg):
    """Copy .example config files to create initial live configs if missing.

    Only copies when the live file does not exist — never overwrites.
    This gives fresh installs a working starting point.
    """
    examples = [
        "freq.toml",
        "hosts.conf",
        "vlans.toml",
        "fleet-boundaries.toml",
        "risk.toml",
        "roles.conf",
        "users.conf",
        "containers.toml",
    ]

    seeded = 0
    for name in examples:
        live = os.path.join(cfg.conf_dir, name)
        example = f"{live}.example"
        if not os.path.isfile(live) and os.path.isfile(example):
            shutil.copy2(example, live)
            seeded += 1

    if seeded:
        fmt.step_ok(f"Seeded {seeded} config file(s) from .example templates")
    else:
        fmt.step_ok("Config files: all present")


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Cluster Configuration
# ═══════════════════════════════════════════════════════════════════

def _update_toml_value(content, key, value):
    """Update a single key = value in TOML content, preserving comments.

    Handles string, list, and boolean values. Works on simple top-level and
    section-level keys. Does NOT handle nested tables or inline tables.
    """
    # Format value for TOML
    if isinstance(value, list):
        items = ', '.join(f'"{v}"' for v in value)
        toml_val = f"[{items}]"
    elif isinstance(value, bool):
        toml_val = "true" if value else "false"
    elif isinstance(value, int):
        toml_val = str(value)
    else:
        toml_val = f'"{value}"'

    # Try to find and replace existing key (commented or not)
    # Match: optional # + optional spaces + key + optional spaces + = + rest of line
    pattern = re.compile(
        r'^([ \t]*#?[ \t]*)(' + re.escape(key) + r')([ \t]*=[ \t]*)(.*)$',
        re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        # Preserve any inline comment after the value
        old_val = match.group(4)
        inline_comment = ""
        # Check if there's an inline comment (not inside a string)
        stripped = old_val.strip()
        if "#" in stripped:
            # Find comment that's not inside quotes
            in_str = False
            for i, ch in enumerate(stripped):
                if ch == '"' and (i == 0 or stripped[i-1] != '\\'):
                    in_str = not in_str
                elif ch == '#' and not in_str:
                    inline_comment = "  " + stripped[i:]
                    break

        # Replace: uncomment if commented, set new value
        new_line = f"{key} = {toml_val}{inline_comment}"
        content = content[:match.start()] + new_line + content[match.end():]
    return content


def _phase_configure(cfg, args=None):
    """Interactive cluster configuration — writes freq.toml with user's details.

    Asks for PVE nodes, network settings, and cluster name. Skips values
    that are already configured (non-empty, non-default) unless user opts to
    reconfigure.
    """
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    if not os.path.isfile(toml_path):
        fmt.step_fail(f"freq.toml not found at {toml_path}")
        return

    with open(toml_path) as f:
        content = f.read()

    changed = False
    yes_flag = getattr(args, "yes", False) if args else False

    # Extract CLI overrides
    cli_pve_nodes = getattr(args, "pve_nodes", None) if args else None
    cli_pve_names = getattr(args, "pve_node_names", None) if args else None
    cli_gateway = getattr(args, "gateway", None) if args else None
    cli_nameserver = getattr(args, "nameserver", None) if args else None
    cli_hosts_file = getattr(args, "hosts_file", None) if args else None
    cli_cluster_name = getattr(args, "cluster_name", None) if args else None
    cli_ssh_mode = getattr(args, "ssh_mode", None) if args else None

    # ── PVE Nodes ──
    if cli_pve_nodes:
        # CLI override — skip interactive prompt
        # Accept both comma-separated and space-separated node lists
        nodes = re.split(r'[,\s]+', cli_pve_nodes.strip())
        names = re.split(r'[,\s]+', cli_pve_names.strip()) if cli_pve_names else [f"pve{i+1:02d}" for i in range(len(nodes))]
        while len(names) < len(nodes):
            names.append(f"pve{len(names)+1:02d}")
        content = _update_toml_value(content, "nodes", nodes)
        content = _update_toml_value(content, "node_names", names)
        cfg.pve_nodes = nodes
        cfg.pve_node_names = names
        changed = True
        fmt.step_ok(f"PVE nodes (from CLI): {', '.join(nodes)}")
    elif cfg.pve_nodes:
        fmt.step_ok(f"PVE nodes already configured: {', '.join(cfg.pve_nodes)}")
        if not yes_flag and _confirm("Reconfigure PVE nodes?"):
            cfg.pve_nodes = []  # force re-prompt below
        # else keep existing

    if not cfg.pve_nodes and not cli_pve_nodes:
        fmt.line(f"  {fmt.C.DIM}Enter your Proxmox VE node IPs (space-separated).{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Example: 192.168.1.10 192.168.1.11 192.168.1.12{fmt.C.RESET}")
        node_input = _input("PVE node IPs")
        if node_input:
            nodes = node_input.split()
            # Ask for node names
            fmt.line(f"  {fmt.C.DIM}Enter names for each node (space-separated, same order).{fmt.C.RESET}")
            name_default = " ".join(f"pve{i+1:02d}" for i in range(len(nodes)))
            name_input = _input("Node names", name_default)
            names = name_input.split()
            # Pad names if fewer than nodes
            while len(names) < len(nodes):
                names.append(f"pve{len(names)+1:02d}")

            content = _update_toml_value(content, "nodes", nodes)
            content = _update_toml_value(content, "node_names", names)
            cfg.pve_nodes = nodes
            cfg.pve_node_names = names
            changed = True
            fmt.step_ok(f"PVE nodes: {', '.join(nodes)}")

            # ── Per-node storage ──
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}Storage pool per node (default: local-lvm).{fmt.C.RESET}")
            for i, name in enumerate(names):
                pool = _input(f"  Storage for {name}", "local-lvm")
                if pool:
                    # Add [pve.storage.<name>] section if not present
                    section = f"[pve.storage.{name}]"
                    if section not in content:
                        # Find insertion point after [pve] section's last key
                        pve_section = content.find("[pve]")
                        if pve_section >= 0:
                            # Find the next section header after [pve]
                            next_section = re.search(r'^\[(?!pve\.)', content[pve_section+5:], re.MULTILINE)
                            if next_section:
                                insert_at = pve_section + 5 + next_section.start()
                            else:
                                insert_at = len(content)
                            storage_block = f"\n{section}\npool = \"{pool}\"\ntype = \"SSD\"\n\n"
                            content = content[:insert_at] + storage_block + content[insert_at:]
                            changed = True
                    else:
                        # Section exists, update the pool value
                        section_pos = content.find(section)
                        pool_pattern = re.compile(
                            r'^(pool\s*=\s*).*$',
                            re.MULTILINE,
                        )
                        section_end = content.find("\n[", section_pos + len(section))
                        if section_end < 0:
                            section_end = len(content)
                        section_text = content[section_pos:section_end]
                        new_section = pool_pattern.sub(f'pool = "{pool}"', section_text)
                        content = content[:section_pos] + new_section + content[section_end:]
                        changed = True
        else:
            fmt.step_warn("No PVE nodes configured — PVE features will be unavailable")

    # ── Gateway ──
    fmt.blank()
    if cli_gateway:
        content = _update_toml_value(content, "gateway", cli_gateway)
        cfg.vm_gateway = cli_gateway
        changed = True
        fmt.step_ok(f"Gateway (from CLI): {cli_gateway}")
    elif cfg.vm_gateway:
        fmt.step_ok(f"Gateway: {cfg.vm_gateway}")
    else:
        fmt.line(f"  {fmt.C.DIM}Your network gateway IP (for VM networking).{fmt.C.RESET}")
        gw = _input("Gateway IP")
        if gw:
            content = _update_toml_value(content, "gateway", gw)
            cfg.vm_gateway = gw
            changed = True
            fmt.step_ok(f"Gateway: {gw}")
        else:
            fmt.step_warn("No gateway set — VM networking may not work")

    # ── Nameserver ──
    if cli_nameserver:
        content = _update_toml_value(content, "nameserver", cli_nameserver)
        cfg.vm_nameserver = cli_nameserver
        changed = True
        fmt.step_ok(f"Nameserver (from CLI): {cli_nameserver}")
    elif cfg.vm_nameserver and cfg.vm_nameserver != "1.1.1.1":
        fmt.step_ok(f"Nameserver: {cfg.vm_nameserver}")
    else:
        ns = _input("DNS nameserver", cfg.vm_nameserver or "1.1.1.1")
        if ns != (cfg.vm_nameserver or "1.1.1.1"):
            content = _update_toml_value(content, "nameserver", ns)
            cfg.vm_nameserver = ns
            changed = True
            fmt.step_ok(f"Nameserver: {ns}")
        else:
            fmt.step_ok(f"Nameserver: {ns} (default)")

    # ── Cluster name ──
    if cli_cluster_name:
        content = _update_toml_value(content, "cluster_name", cli_cluster_name)
        cfg.cluster_name = cli_cluster_name
        changed = True
        fmt.step_ok(f"Cluster (from CLI): {cli_cluster_name}")
    elif cfg.cluster_name:
        fmt.step_ok(f"Cluster: {cfg.cluster_name}")
    else:
        name = _input("Cluster name (optional, e.g. dc01, homelab)")
        if name:
            content = _update_toml_value(content, "cluster_name", name)
            cfg.cluster_name = name
            changed = True
            fmt.step_ok(f"Cluster: {name}")

    # ── SSH mode ──
    if cli_ssh_mode:
        if cli_ssh_mode != cfg.ssh_mode:
            content = _update_toml_value(content, "mode", cli_ssh_mode)
            cfg.ssh_mode = cli_ssh_mode
            changed = True
        fmt.step_ok(f"SSH mode (from CLI): {cli_ssh_mode}")
    else:
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}SSH mode: 'sudo' = SSH as service account + sudo (recommended){fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}          'root' = SSH as root directly{fmt.C.RESET}")
        mode = _input("SSH mode", cfg.ssh_mode or "sudo")
        if mode in ("sudo", "root") and mode != cfg.ssh_mode:
            content = _update_toml_value(content, "mode", mode)
            cfg.ssh_mode = mode
            changed = True
        fmt.step_ok(f"SSH mode: {mode}")

    # ── Write changes ──
    if changed:
        with open(toml_path, "w") as f:
            f.write(content)
        fmt.blank()
        fmt.step_ok(f"Configuration saved to {toml_path}")
        # Reload config to pick up changes
        try:
            from freq.core.config import load_config
            new_cfg = load_config(cfg.install_dir)
            cfg.pve_nodes = new_cfg.pve_nodes
            cfg.pve_node_names = new_cfg.pve_node_names
            cfg.pve_storage = new_cfg.pve_storage
            cfg.vm_gateway = new_cfg.vm_gateway
            cfg.vm_nameserver = new_cfg.vm_nameserver
            cfg.cluster_name = new_cfg.cluster_name
            cfg.ssh_mode = new_cfg.ssh_mode
            cfg.hosts = new_cfg.hosts
            fmt.step_ok(f"Config reloaded: {len(cfg.pve_nodes)} PVE nodes, {len(cfg.hosts)} hosts")
        except Exception as e:
            fmt.step_warn(f"Config reload issue: {e} — continuing with current values")
    else:
        fmt.step_ok("Configuration unchanged — all values already set")


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Service Account
# ═══════════════════════════════════════════════════════════════════

def _phase_service_account(cfg, ctx, args=None):
    """Create service account with NOPASSWD sudo."""
    fmt.line(f"  {fmt.C.DIM}The service account is used for fleet-wide SSH operations.{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}It will be created on this host and deployed to all managed nodes.{fmt.C.RESET}")
    fmt.blank()

    # Service account name
    svc_name = _input("Service account name", ctx["svc_name"])
    if not _validate_username(svc_name):
        fmt.step_fail(f"Invalid username '{svc_name}' — must be lowercase, start with letter/underscore, max 32 chars")
        return 1
    ctx["svc_name"] = svc_name
    fmt.blank()

    # Read password from file if provided, otherwise prompt
    pw_file = getattr(args, "password_file", None) if args else None
    file_pass = None
    if pw_file:
        if os.path.isfile(pw_file):
            with open(pw_file) as f:
                file_pass = f.read().strip()
            if not file_pass:
                fmt.step_fail(f"Password file is empty: {pw_file}")
                return False
            if len(file_pass) < 4:
                fmt.step_fail("Password too short (min 4 characters)")
                return False
            fmt.step_ok(f"Password loaded from {pw_file}")
        else:
            fmt.step_fail(f"Password file not found: {pw_file}")
            return False

    # Check if account exists
    rc, _, _ = _run(["id", svc_name])
    if rc == 0:
        fmt.step_ok(f"Account '{svc_name}' already exists")
        # Check sudo
        rc2, _, _ = _run(["sudo", "-u", svc_name, "sudo", "-n", "true"])
        if rc2 == 0:
            fmt.step_ok("Has NOPASSWD sudo")
        else:
            fmt.step_warn("No NOPASSWD sudo — setting up...")
            _setup_sudoers(svc_name)

        # Get password for vault + remote deployment
        if file_pass:
            svc_pass = file_pass
        else:
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}Enter password for '{svc_name}' (for vault + remote deployment){fmt.C.RESET}")
            svc_pass = _read_password(f"Password for '{svc_name}'")
        if not svc_pass:
            fmt.step_fail("Password required")
            return False
        ctx["svc_pass"] = svc_pass
    else:
        # Create account
        fmt.line(f"  {fmt.C.DIM}Creating service account '{svc_name}'...{fmt.C.RESET}")
        fmt.blank()

        if file_pass:
            svc_pass = file_pass
        else:
            svc_pass = _read_password(f"Password for '{svc_name}'")
        if not svc_pass:
            fmt.step_fail("Password required")
            return False
        ctx["svc_pass"] = svc_pass

        # useradd — creates matching group automatically
        cmd = ["useradd", "-m", "-s", "/bin/bash", svc_name]
        _run(cmd)

        rc3, _, _ = _run(["id", svc_name])
        if rc3 == 0:
            fmt.step_ok(f"Account '{svc_name}' created")
        else:
            fmt.step_fail(f"Failed to create account '{svc_name}'")
            return False

        # Set password
        p = subprocess.Popen(["/usr/sbin/chpasswd"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.communicate(input=f"{svc_name}:{svc_pass}\n".encode())
        if p.returncode == 0:
            fmt.step_ok("Password set")
        else:
            fmt.step_warn("chpasswd failed — password may not be set")

        # Sudoers
        _setup_sudoers(svc_name)

    # Initialize vault if needed
    if not os.path.exists(cfg.vault_file):
        from freq.modules.vault import vault_init
        if not vault_init(cfg):
            fmt.step_fail("Vault init failed — check /etc/machine-id exists")
            return False

    # Store password in vault
    from freq.modules.vault import vault_set
    vault_key = f"{svc_name}-pass"
    if vault_set(cfg, "DEFAULT", vault_key, ctx["svc_pass"]):
        fmt.step_ok(f"Password stored in vault (key: {vault_key})")
    else:
        fmt.step_fail(f"Failed to store password in vault (key: {vault_key})")

    # Update config
    _update_toml(cfg, "ssh", "service_account", svc_name)
    fmt.step_ok(f"Config updated: service_account = {svc_name}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Remember this password — it's your break-glass access (su - {svc_name}){fmt.C.RESET}")

    return True


def _setup_sudoers(svc_name):
    """Configure NOPASSWD sudo for service account."""
    sudoers_file = f"/etc/sudoers.d/freq-{svc_name}"
    try:
        with open(sudoers_file, "w") as f:
            f.write(f"{svc_name} ALL=(ALL) NOPASSWD: ALL\n")
        os.chmod(sudoers_file, 0o440)

        # Validate
        rc, _, _ = _run(["visudo", "-cf", sudoers_file])
        if rc == 0:
            fmt.step_ok(f"Sudoers configured: {sudoers_file} (validated)")
        else:
            os.unlink(sudoers_file)
            fmt.step_fail("Sudoers validation failed — removed")
    except PermissionError:
        fmt.step_fail("Cannot write sudoers (not root?)")


def _ssh_with_pass(password, ssh_cmd_list, timeout=DEFAULT_CMD_TIMEOUT, input_text=None):
    """Run SSH command using sshpass with secure tempfile (not process-visible).

    Writes password to a chmod-600 tempfile, uses 'sshpass -f', then deletes.
    If input_text is provided, pipes it via stdin (for IOS switch config).
    Returns (rc, stdout, stderr).
    """
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.freq-auth', delete=False)
    try:
        tmp.write(password)
        tmp.close()
        os.chmod(tmp.name, 0o600)
        full_cmd = ["sshpass", "-f", tmp.name] + ssh_cmd_list
        if input_text is not None:
            return _run_with_input(full_cmd, input_text, timeout=timeout)
        return _run(full_cmd, timeout=timeout)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError as e:
            logger.warn(f"failed to clean temp auth file: {e}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 4: SSH Keys
# ═══════════════════════════════════════════════════════════════════

def _phase_ssh_keys(cfg, ctx):
    """Generate FREQ SSH keypairs and deploy to local service account.

    Two keys are generated:
    - freq_id_ed25519: modern hosts (linux, pve, docker, truenas, pfsense)
    - freq_id_rsa: legacy devices (iDRAC, Cisco switch) that don't support ed25519
    """
    key_dir = cfg.key_dir
    hostname = os.uname().nodename
    os.makedirs(key_dir, mode=0o700, exist_ok=True)

    # --- ed25519 key (primary — modern hosts) ---
    ed_key = os.path.join(key_dir, "freq_id_ed25519")
    if os.path.isfile(ed_key):
        fmt.step_ok("FREQ ed25519 key already exists")
        os.chmod(ed_key, 0o600)  # Enforce correct permissions
        if os.path.isfile(f"{ed_key}.pub"):
            os.chmod(f"{ed_key}.pub", 0o644)
        rc, out, _ = _run(["ssh-keygen", "-l", "-f", f"{ed_key}.pub"])
        if rc == 0:
            fmt.line(f"    {fmt.C.DIM}{out.strip()}{fmt.C.RESET}")
    else:
        fmt.step_start("Generating ed25519 keypair (modern hosts)")
        rc, _, err = _run([
            "ssh-keygen", "-t", "ed25519",
            "-C", f"freq@{hostname}",
            "-f", ed_key, "-N", "", "-q",
        ])
        if rc == 0:
            os.chmod(ed_key, 0o600)
            os.chmod(f"{ed_key}.pub", 0o644)
            fmt.step_ok("FREQ ed25519 key generated")
        else:
            fmt.step_fail(f"ed25519 key generation failed: {err[:60]}")
            return

    # --- RSA key (legacy — iDRAC, Cisco switch) ---
    rsa_key = os.path.join(key_dir, "freq_id_rsa")
    if os.path.isfile(rsa_key):
        fmt.step_ok("FREQ RSA key already exists (legacy devices)")
        os.chmod(rsa_key, 0o600)  # Enforce correct permissions
        if os.path.isfile(f"{rsa_key}.pub"):
            os.chmod(f"{rsa_key}.pub", 0o644)
        rc, out, _ = _run(["ssh-keygen", "-l", "-f", f"{rsa_key}.pub"])
        if rc == 0:
            fmt.line(f"    {fmt.C.DIM}{out.strip()}{fmt.C.RESET}")
    else:
        fmt.step_start("Generating RSA-4096 keypair (iDRAC + switch)")
        rc, _, err = _run([
            "ssh-keygen", "-t", "rsa", "-b", "4096",
            "-C", f"freq-legacy@{hostname}",
            "-f", rsa_key, "-N", "", "-q",
        ])
        if rc == 0:
            os.chmod(rsa_key, 0o600)
            os.chmod(f"{rsa_key}.pub", 0o644)
            fmt.step_ok("FREQ RSA-4096 key generated (for iDRAC + switch)")
        else:
            fmt.step_warn(f"RSA key generation failed: {err[:60]} — iDRAC/switch will need manual setup")

    ctx["key_path"] = ed_key
    ctx["rsa_key_path"] = rsa_key

    # Fix ownership — init runs as root but keys need to be readable by
    # the service account and whoever runs the dashboard.
    # The invoking user (SUDO_USER) is the real operator.
    real_user = os.environ.get("SUDO_USER", "")
    if real_user:
        for f in [key_dir, ed_key, f"{ed_key}.pub", rsa_key, f"{rsa_key}.pub"]:
            if os.path.exists(f):
                _run(["chown", f"{real_user}:{real_user}", f])
        fmt.step_ok(f"Key ownership set to {real_user}")

    # Read public keys
    ed_pub = f"{ed_key}.pub"
    if os.path.isfile(ed_pub):
        with open(ed_pub) as f:
            ctx["pubkey"] = f.read().strip()

    rsa_pub = f"{rsa_key}.pub"
    if os.path.isfile(rsa_pub):
        with open(rsa_pub) as f:
            ctx["rsa_pubkey"] = f.read().strip()

    # Deploy to local service account
    svc_name = ctx["svc_name"]
    rc, out, _ = _run(["getent", "passwd", svc_name])
    if rc == 0:
        svc_home = out.strip().split(":")[5]
        ssh_dir = os.path.join(svc_home, ".ssh")
        auth_keys = os.path.join(ssh_dir, "authorized_keys")

        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        _run(["chown", f"{svc_name}:{svc_name}", ssh_dir])

        if ctx["pubkey"]:
            # Check if already in authorized_keys
            existing = ""
            if os.path.isfile(auth_keys):
                with open(auth_keys) as f:
                    existing = f.read()
            if ctx["pubkey"] not in existing:
                with open(auth_keys, "a") as f:
                    f.write(ctx["pubkey"] + "\n")
            os.chmod(auth_keys, 0o600)
            _run(["chown", f"{svc_name}:{svc_name}", auth_keys])
            fmt.step_ok(f"ed25519 public key deployed to local {svc_name}")

    # Also copy keys to service account's .ssh for outbound SSH
    if rc == 0 and ctx.get("key_path"):
        import shutil
        svc_ssh = os.path.join(svc_home, ".ssh")

        # ed25519 (primary)
        svc_ed = os.path.join(svc_ssh, "id_ed25519")
        if not os.path.isfile(svc_ed):
            shutil.copy2(ctx["key_path"], svc_ed)
            shutil.copy2(f"{ctx['key_path']}.pub", f"{svc_ed}.pub")
            os.chmod(svc_ed, 0o600)
            _run(["chown", f"{svc_name}:{svc_name}", svc_ed, f"{svc_ed}.pub"])
            fmt.step_ok(f"ed25519 private key copied to {svc_name}/.ssh/")

        # RSA (legacy)
        if os.path.isfile(rsa_key):
            svc_rsa = os.path.join(svc_ssh, "id_rsa")
            if not os.path.isfile(svc_rsa):
                shutil.copy2(rsa_key, svc_rsa)
                shutil.copy2(f"{rsa_key}.pub", f"{svc_rsa}.pub")
                os.chmod(svc_rsa, 0o600)
                _run(["chown", f"{svc_name}:{svc_name}", svc_rsa, f"{svc_rsa}.pub"])
                fmt.step_ok(f"RSA private key copied to {svc_name}/.ssh/")

    # RSA key status for legacy devices
    if os.path.isfile(rsa_pub):
        fmt.step_ok("RSA key ready for automated iDRAC/switch deployment")


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: PVE Node Deployment
# ═══════════════════════════════════════════════════════════════════

def _phase_pve_deploy(cfg, ctx, args=None):
    """Deploy service account + key to PVE nodes."""
    pve_nodes = cfg.pve_nodes

    if not pve_nodes:
        fmt.line(f"  {fmt.C.DIM}No PVE nodes configured.{fmt.C.RESET}")
        node_input = _input("Enter PVE node IPs (space-separated), or press Enter to skip")
        if not node_input:
            fmt.step_warn("Skipping PVE deployment")
            return
        pve_nodes = node_input.split()

    fmt.line(f"  {fmt.C.DIM}PVE nodes to deploy:{fmt.C.RESET}")
    for ip in pve_nodes:
        fmt.line(f"    {fmt.C.CYAN}{ip}{fmt.C.RESET}")
    fmt.blank()

    # Check for CLI bootstrap credentials (--bootstrap-key, --bootstrap-user, --bootstrap-password-file)
    bootstrap_key = getattr(args, "bootstrap_key", None) if args else None
    bootstrap_user = getattr(args, "bootstrap_user", None) if args else None
    bootstrap_pass_file = getattr(args, "bootstrap_password_file", None) if args else None

    # Read bootstrap password from file if provided
    bootstrap_pass = ""
    if bootstrap_pass_file and os.path.isfile(bootstrap_pass_file):
        with open(bootstrap_pass_file) as f:
            bootstrap_pass = f.read().strip()

    if bootstrap_key and os.path.isfile(bootstrap_key):
        # Bootstrap key mode — skip interactive prompts
        pve_user = bootstrap_user or "root"
        auth_key = bootstrap_key
        auth_pass = ""
        fmt.step_ok(f"Using bootstrap key auth: {pve_user} via {auth_key}")
    elif bootstrap_pass:
        # Bootstrap password mode — use sshpass
        pve_user = bootstrap_user or "root"
        auth_key = ""
        auth_pass = bootstrap_pass
        rc, _, _ = _run(["which", "sshpass"])
        if rc != 0:
            fmt.step_fail("'sshpass' not installed — required for --bootstrap-password-file")
            from freq.core.packages import install_hint
            fmt.line(f"  {fmt.C.DIM}Install with: {install_hint('sshpass')}{fmt.C.RESET}")
            return
        fmt.step_ok(f"Using bootstrap password auth: {pve_user} via sshpass")
    else:
        # Interactive mode
        pve_user = _input("Deploy as user (root or sudo account)", "root")

        fmt.line(f"  {fmt.C.DIM}How to authenticate to PVE nodes as '{pve_user}'?{fmt.C.RESET}")
        fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Password")
        fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
        fmt.blank()

        auth_choice = _input("Choice", "A").upper()
        auth_pass = ""
        auth_key = ""

        if auth_choice == "B":
            auth_key = _input("SSH key path", os.path.expanduser("~/.ssh/id_ed25519"))
            if not os.path.isfile(auth_key):
                fmt.step_warn(f"Key not found: {auth_key} — falling back to password")
                auth_key = ""

        if not auth_key:
            rc, _, _ = _run(["which", "sshpass"])
            if rc != 0:
                fmt.step_fail("'sshpass' not installed — required for password-based SSH")
                from freq.core.packages import install_hint
                fmt.line(f"  {fmt.C.DIM}Install with: {install_hint('sshpass')}{fmt.C.RESET}")
                fmt.line(f"  {fmt.C.DIM}Or choose option B (SSH key) instead.{fmt.C.RESET}")
                return
            auth_pass = getpass.getpass(f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for '{pve_user}' on PVE nodes: ")

    if pve_user != "root":
        fmt.line(f"  {fmt.C.DIM}Commands will be elevated via sudo on remote hosts.{fmt.C.RESET}")
        fmt.blank()

    # Deploy to each node
    ok = fail = 0
    for ip in pve_nodes:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}{ip}{fmt.C.RESET}")
        if _deploy_to_host_dispatch(ip, "pve", ctx, auth_pass, auth_key, pve_user):
            ok += 1
        else:
            fail += 1

    fmt.blank()
    fmt.line(f"  PVE deployment: {fmt.C.GREEN}{ok} OK{fmt.C.RESET}, {fmt.C.RED}{fail} failed{fmt.C.RESET}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 6: Fleet Host Deployment
# ═══════════════════════════════════════════════════════════════════

def _register_host_interactive(cfg):
    """Prompt user to manually register a single host. Returns True if added."""
    try:
        ip = input(f"    {fmt.C.CYAN}IP address:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not ip:
        return False

    # Basic IP validation
    octets = ip.split(".")
    if len(octets) != 4:
        fmt.step_fail(f"Invalid IP: {ip}")
        return False
    try:
        for o in octets:
            v = int(o)
            if v < 0 or v > 255:
                raise ValueError
    except ValueError:
        fmt.step_fail(f"Invalid IP: {ip}")
        return False

    # Check duplicate
    for h in cfg.hosts:
        if h.ip == ip:
            fmt.step_warn(f"{ip} already registered as '{h.label}'")
            return False

    label = _input("  Label (e.g. plex, truenas, pfsense01)")
    if not label:
        return False
    if not _validate_label(label):
        fmt.step_fail(f"Invalid label '{label}' — must be alphanumeric, max 64 chars")
        return False

    valid_types = ["linux", "pve", "truenas", "pfsense", "docker", "idrac", "switch"]
    htype = _input(f"  Type ({', '.join(valid_types)})", "linux").lower()
    if htype not in valid_types:
        fmt.step_fail(f"Invalid type: {htype}")
        return False

    groups = _input("  Groups (comma-separated, optional)", "")

    line = f"{ip}  {label}  {htype}"
    if groups:
        line += f"  {groups}"

    with open(cfg.hosts_file, "a") as f:
        f.write(f"{line}\n")

    # Reload hosts list
    from freq.core.config import Host
    cfg.hosts.append(Host(ip=ip, label=label, htype=htype, groups=groups))

    fmt.step_ok(f"Registered: {label} ({ip}) [{htype}]")
    return True


def _discover_and_register(cfg, ctx):
    """Run network discovery and offer to register found hosts."""
    from freq.modules.discover import scan_and_identify, _display_discovery_results, _parse_subnet_input

    subnet = _input("Subnet to scan (e.g. 192.168.1 or 192.168.1.0/24)")
    if not subnet:
        return

    prefix, start, end = _parse_subnet_input(subnet)
    if prefix is None:
        fmt.step_fail(f"Invalid subnet: {subnet}")
        fmt.line(f"    {fmt.C.DIM}Examples: 192.168.1  or  192.168.1.0/24{fmt.C.RESET}")
        return

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Scanning {prefix}.{start}-{end}...{fmt.C.RESET}")
    fmt.blank()

    key_path = ctx.get("key_path", "") or cfg.ssh_key_path
    alive, hosts_info = scan_and_identify(prefix, key_path, start, end, cfg=cfg)

    if not alive:
        fmt.blank()
        fmt.line(f"  {fmt.C.YELLOW}No hosts found on {prefix}.0/24{fmt.C.RESET}")
        return

    known_ips = {h.ip for h in cfg.hosts}
    ssh_reachable = sum(1 for h in hosts_info if h["reachable"])
    new_count = _display_discovery_results(alive, hosts_info, known_ips)

    if new_count == 0:
        fmt.blank()
        if ssh_reachable == 0:
            svc = cfg.ssh_service_account or "freq-admin"
            fmt.line(f"  {fmt.C.YELLOW}No hosts could be identified via SSH.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Tried connecting as '{svc}'. Hosts need this account + key first.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Use 'freq hosts add' to register hosts manually, then deploy keys.{fmt.C.RESET}")
        else:
            fmt.line(f"  {fmt.C.GREEN}All discovered hosts are already registered.{fmt.C.RESET}")
        return

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}{new_count} new host(s) found.{fmt.C.RESET}")
    fmt.blank()

    # Offer to register discovered hosts
    from freq.core.config import Host
    for h in hosts_info:
        if not h["reachable"] or h["ip"] in known_ips:
            continue

        hostname = h["hostname"] or "unknown"
        detected_type = h["type"]

        fmt.line(f"  {fmt.C.CYAN}{h['ip']}{fmt.C.RESET} — {hostname} [{detected_type}]")
        if not _confirm(f"  Register this host?", default=True):
            continue

        label = _input(f"    Label", hostname)
        htype = _input(f"    Type", detected_type)
        groups = _input(f"    Groups (optional)", "")

        line = f"{h['ip']}  {label}  {htype}"
        if groups:
            line += f"  {groups}"

        with open(cfg.hosts_file, "a") as f:
            f.write(f"{line}\n")

        cfg.hosts.append(Host(ip=h["ip"], label=label, htype=htype, groups=groups))
        known_ips.add(h["ip"])
        fmt.step_ok(f"Registered: {label} ({h['ip']}) [{htype}]")

    # Offer to scan another subnet
    fmt.blank()
    if _confirm("Scan another subnet?"):
        _discover_and_register(cfg, ctx)


# ═══════════════════════════════════════════════════════════════════
# PHASE 6: PDM Setup (detect / install / configure)
# ═══════════════════════════════════════════════════════════════════

def _pdm_is_installed():
    """Check if PDM is installed on this host."""
    rc, _, _ = _run(["systemctl", "is-active", "proxmox-datacenter-api"])
    return rc == 0


def _pdm_install():
    """Install PDM from Proxmox repos (Debian 13/trixie only).

    Returns True on success.
    """
    fmt.step_start("Checking OS compatibility...")

    # Verify Debian trixie
    rc, out, _ = _run(["cat", "/etc/os-release"])
    if rc != 0 or "trixie" not in out.lower():
        fmt.step_fail("PDM requires Debian 13 (trixie)")
        fmt.line(f"  {fmt.C.DIM}Install PDM manually or use a Debian 13 host.{fmt.C.RESET}")
        return False

    fmt.step_ok("Debian 13 (trixie) detected")

    # Add GPG key
    fmt.step_start("Adding Proxmox GPG key...")
    rc, _, err = _run([
        "wget", "-qO", "/etc/apt/trusted.gpg.d/proxmox-release-trixie.gpg",
        "https://enterprise.proxmox.com/debian/proxmox-release-trixie.gpg",
    ], timeout=30)
    if rc != 0:
        fmt.step_fail(f"Failed to download GPG key: {err.strip()}")
        return False
    fmt.step_ok("GPG key installed")

    # Add repo
    fmt.step_start("Adding PDM repository...")
    repo_line = "deb http://download.proxmox.com/debian/pdm trixie pdm-no-subscription"
    repo_path = "/etc/apt/sources.list.d/pdm.list"
    try:
        with open(repo_path, "w") as f:
            f.write(repo_line + "\n")
        fmt.step_ok("Repository added")
    except OSError as e:
        fmt.step_fail(f"Cannot write {repo_path}: {e}")
        return False

    # apt update
    fmt.step_start("Updating package lists...")
    rc, _, err = _run(["apt-get", "update", "-qq"], timeout=120)
    if rc != 0:
        fmt.step_fail(f"apt-get update failed: {err.strip()[:200]}")
        return False
    fmt.step_ok("Package lists updated")

    # Install PDM
    fmt.step_start("Installing proxmox-datacenter-manager (this may take a few minutes)...")
    rc, _, err = _run([
        "apt-get", "install", "-y", "proxmox-datacenter-manager",
    ], timeout=600)
    if rc != 0:
        fmt.step_fail(f"Installation failed: {err.strip()[:200]}")
        return False

    # Verify services started
    rc, _, _ = _run(["systemctl", "is-active", "proxmox-datacenter-api"])
    if rc != 0:
        fmt.step_warn("PDM installed but service not running — try: systemctl start proxmox-datacenter-api")
        return False

    fmt.step_ok("PDM installed and running")
    return True


def _pdm_api_request(method, path, data=None, cookies=None, csrf_token=None):
    """Make an HTTP request to the local PDM API.

    Returns (success, response_dict_or_error_string).
    """
    import json
    import urllib.request
    import urllib.error
    import ssl

    url = f"https://localhost:8443{path}"

    # PDM uses self-signed certs
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    if data and method == "POST":
        # URL-encode form data
        import urllib.parse
        if isinstance(data, dict):
            # Handle repeated params (e.g. nodes=[...])
            parts = []
            for k, v in data.items():
                if isinstance(v, list):
                    for item in v:
                        parts.append((k, item))
                else:
                    parts.append((k, v))
            body = urllib.parse.urlencode(parts).encode()
        else:
            body = data.encode() if isinstance(data, str) else data
    else:
        body = None

    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if csrf_token:
        req.add_header("CSRFPreventionToken", csrf_token)
    if cookies:
        req.add_header("Cookie", cookies)

    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            raw = resp.read().decode()
            # Extract Set-Cookie for auth flow
            set_cookie = resp.headers.get("Set-Cookie", "")
            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                result = {"raw": raw}
            return True, result, set_cookie
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except (OSError, UnicodeDecodeError, AttributeError):
            pass
        return False, f"HTTP {e.code}: {body}", ""
    except Exception as e:
        return False, str(e), ""


def _pdm_authenticate(password):
    """Authenticate to PDM API, return (cookies, csrf_token) or (None, None).

    PDM v1.0.3 returns the auth ticket via Set-Cookie header (not in JSON body).
    The JSON body contains CSRFPreventionToken and ticket-info.
    """
    ok, result, set_cookie = _pdm_api_request("POST", "/api2/json/access/ticket", {
        "username": "root@pam",
        "password": password,
    })
    if not ok:
        return None, None

    data = result.get("data", {})
    csrf = data.get("CSRFPreventionToken", "")

    # PDM returns ticket via Set-Cookie header, not JSON body
    # Extract __Host-PDMAuthCookie from Set-Cookie header
    cookie_str = ""
    if set_cookie and "__Host-PDMAuthCookie=" in set_cookie:
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("__Host-PDMAuthCookie="):
                cookie_str = part
                break

    # Fallback: check JSON body (older PDM versions may include ticket there)
    if not cookie_str:
        ticket = data.get("ticket", "")
        if ticket:
            cookie_str = f"__Host-PDMAuthCookie={ticket}"

    if not cookie_str or not csrf:
        return None, None

    return cookie_str, csrf


def _pdm_probe_tls(ip, cookies, csrf):
    """Probe TLS fingerprint for a PVE node. Returns fingerprint string or None."""
    ok, result, _ = _pdm_api_request("POST", "/api2/json/pve/probe-tls", {
        "hostname": ip,
    }, cookies=cookies, csrf_token=csrf)
    if not ok:
        return None
    data = result.get("data", {})
    return data.get("fingerprint")


def _pdm_add_remote(remote_name, token_id, token_secret, node_entries, cookies, csrf):
    """Add a PVE cluster as a PDM remote.

    node_entries: list of "IP,fingerprint=XX:XX:..." strings
    Returns True on success.
    """
    data = {
        "id": remote_name,
        "type": "pve",
        "authid": token_id,
        "token": token_secret,
        "nodes": node_entries,
    }
    ok, result, _ = _pdm_api_request("POST", "/api2/json/remotes/remote", data,
                                      cookies=cookies, csrf_token=csrf)
    return ok


def _pdm_create_pve_token(pve_ip, ctx):
    """Create pdm@pve user and API token on a PVE node via SSH.

    Uses the already-deployed freq service account for SSH access.
    Returns (token_id, token_secret) or (None, None).
    """
    key_path = ctx.get("key_path", "")
    svc_name = ctx.get("svc_name", "freq-admin")

    ssh_base = [
        "ssh", "-n",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-i", key_path,
        f"{svc_name}@{pve_ip}",
    ]

    # Check if pdm@pve user already exists
    rc, out, _ = _run(ssh_base + ["sudo pveum user list --output-format json 2>/dev/null"])
    pdm_user_exists = "pdm@pve" in out if rc == 0 else False

    if not pdm_user_exists:
        # Create pdm@pve user
        rc, _, err = _run(ssh_base + ["sudo pveum user add pdm@pve --comment 'PDM API access'"])
        if rc != 0:
            fmt.step_fail(f"Failed to create pdm@pve user: {err.strip()[:200]}")
            return None, None

        # Grant PVEAuditor role
        rc, _, err = _run(ssh_base + ["sudo pveum acl modify / --roles PVEAuditor --users pdm@pve"])
        if rc != 0:
            fmt.step_warn(f"Failed to set PVEAuditor role: {err.strip()[:200]}")

    # Create API token (--privsep 0 = full user privileges)
    # If token already exists, delete and recreate (PVE only shows secret at creation)
    rc, out, err = _run(ssh_base + ["sudo pveum user token add pdm@pve pdm --privsep 0 --output-format json 2>&1"])
    if rc != 0 and "already exists" in (err + out):
        # Token exists — delete and recreate to get the secret
        _run(ssh_base + ["sudo pveum user token remove pdm@pve pdm"])
        rc, out, err = _run(ssh_base + ["sudo pveum user token add pdm@pve pdm --privsep 0 --output-format json 2>&1"])
    if rc != 0:
        fmt.step_fail(f"Failed to create API token: {err.strip()[:200]}")
        return None, None

    # Parse token output
    import json
    try:
        token_data = json.loads(out)
        # PVE returns: {"full-tokenid": "pdm@pve!pdm", "info": {...}, "value": "UUID-SECRET"}
        token_id = token_data.get("full-tokenid", "pdm@pve!pdm")
        token_secret = token_data.get("value", "")
        if not token_secret:
            fmt.step_fail("Token created but no secret returned")
            return None, None
        return token_id, token_secret
    except (json.JSONDecodeError, ValueError):
        # Try plain text parse: "full-tokenid: ...\nvalue: ..."
        token_id = "pdm@pve!pdm"
        for line in out.split("\n"):
            if "value" in line.lower() and ":" in line:
                token_secret = line.split(":", 1)[1].strip().strip('"')
                return token_id, token_secret
        fmt.step_fail("Could not parse token output")
        return None, None


def _phase_pdm(cfg, ctx, args=None):
    """PDM setup phase — detect, optionally install, configure remote."""
    skip_pdm = getattr(args, "skip_pdm", False) if args else False
    install_pdm = getattr(args, "install_pdm", False) if args else False
    remote_name = getattr(args, "pdm_remote_name", None) if args else None
    headless = getattr(args, "headless", False) if args else False

    if skip_pdm:
        fmt.step_warn("PDM setup skipped (--skip-pdm)")
        return

    # Step 1: Detect PDM
    fmt.line(f"  {fmt.C.DIM}Checking for Proxmox Datacenter Manager...{fmt.C.RESET}")
    fmt.blank()

    pdm_running = _pdm_is_installed()

    if pdm_running:
        fmt.step_ok("PDM detected (proxmox-datacenter-api is active)")
    else:
        fmt.line(f"  {fmt.C.DIM}PDM is not installed.{fmt.C.RESET}")
        fmt.blank()

        if headless:
            if not install_pdm:
                fmt.step_warn("PDM not installed — use --install-pdm to install in headless mode")
                return
            # Headless install
            fmt.step_start("Installing PDM (headless)...")
            if not _pdm_install():
                fmt.step_warn("PDM installation failed — continuing without PDM")
                return
            pdm_running = True
        else:
            # Interactive — ask
            fmt.line(f"  {fmt.C.BOLD}PDM provides:{fmt.C.RESET} unified dashboard, cross-node migration,")
            fmt.line(f"  capacity planning, aggregated tasks across your PVE cluster.")
            fmt.blank()
            if _confirm("Install PDM? (recommended for multi-node clusters)"):
                if not _pdm_install():
                    fmt.step_warn("PDM installation failed — continuing without PDM")
                    return
                pdm_running = True
            else:
                fmt.step_warn("Skipping PDM — freq works fully without it")
                fmt.line(f"  {fmt.C.DIM}Install later: apt install proxmox-datacenter-manager{fmt.C.RESET}")
                return

    # Step 2: Configure PVE remote (if we have PVE nodes)
    if not cfg.pve_nodes:
        fmt.line(f"  {fmt.C.DIM}No PVE nodes configured — skipping remote setup.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Add PVE nodes later and re-run init to configure PDM.{fmt.C.RESET}")
        return

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Configuring PVE cluster remote...{fmt.C.RESET}")
    fmt.blank()

    # Get PDM admin password for API auth
    # Priority: --pdm-pass file > PDM_PASSWORD env var > interactive prompt
    pdm_pass_file = getattr(args, "pdm_pass", None) if args else None
    pdm_pass = ""
    if pdm_pass_file and os.path.isfile(pdm_pass_file):
        with open(pdm_pass_file) as f:
            pdm_pass = f.read().strip()
        if pdm_pass:
            fmt.step_ok(f"PDM password loaded from {pdm_pass_file}")

    if not pdm_pass:
        pdm_pass = os.environ.get("PDM_PASSWORD", "")
        if pdm_pass:
            fmt.step_ok("PDM password loaded from PDM_PASSWORD env var")

    if headless:
        if not pdm_pass:
            fmt.step_warn("PDM remote setup requires authentication")
            fmt.line(f"  {fmt.C.DIM}Use --pdm-pass FILE or set PDM_PASSWORD env var{fmt.C.RESET}")
            return
    else:
        fmt.line(f"  {fmt.C.DIM}PDM web UI: https://localhost:8443{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Login as root@pam (system root password){fmt.C.RESET}")
        fmt.blank()
        if not _confirm("Configure PVE cluster remote now?"):
            fmt.step_warn("Skipping remote setup — configure manually via PDM web UI")
            return
        if not pdm_pass:
            pdm_pass = getpass.getpass(f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  PDM root password (root@pam): ")

    # Authenticate to PDM
    fmt.step_start("Authenticating to PDM API...")
    cookies, csrf = _pdm_authenticate(pdm_pass)
    if not cookies:
        fmt.step_fail("PDM authentication failed — check root password")
        fmt.line(f"  {fmt.C.DIM}Configure manually: https://localhost:8443{fmt.C.RESET}")
        return
    fmt.step_ok("Authenticated to PDM")

    # Create PVE API token on first node
    first_node = cfg.pve_nodes[0] if isinstance(cfg.pve_nodes, list) else cfg.pve_nodes.split()[0]
    fmt.step_start(f"Creating pdm@pve API token on {first_node}...")

    token_id, token_secret = _pdm_create_pve_token(first_node, ctx)
    if not token_id:
        fmt.step_fail("Could not create PVE API token")
        fmt.line(f"  {fmt.C.DIM}Create manually: pveum user add pdm@pve && pveum user token add pdm@pve pdm --privsep 0{fmt.C.RESET}")
        return
    fmt.step_ok(f"Token created: {token_id}")

    # Probe TLS fingerprints for all PVE nodes
    pve_node_list = cfg.pve_nodes if isinstance(cfg.pve_nodes, list) else cfg.pve_nodes.split()
    node_entries = []
    for node_ip in pve_node_list:
        fmt.step_start(f"Probing TLS fingerprint for {node_ip}...")
        fp = _pdm_probe_tls(node_ip, cookies, csrf)
        if fp:
            node_entries.append(f"{node_ip},fingerprint={fp}")
            fmt.step_ok(f"{node_ip}: {fp[:20]}...")
        else:
            fmt.step_fail(f"Could not probe TLS for {node_ip}")

    if not node_entries:
        fmt.step_fail("No PVE nodes reachable — cannot add remote")
        return

    # Add remote
    if not remote_name:
        remote_name = getattr(cfg, "cluster_name", "") or "pve-cluster"
    fmt.step_start(f"Adding remote '{remote_name}' ({len(node_entries)} node(s))...")

    if _pdm_add_remote(remote_name, token_id, token_secret, node_entries, cookies, csrf):
        fmt.step_ok(f"Remote '{remote_name}' added to PDM")
        fmt.blank()
        fmt.line(f"  {fmt.C.GREEN}PDM configured!{fmt.C.RESET} Dashboard: {fmt.C.CYAN}https://localhost:8443{fmt.C.RESET}")
    else:
        fmt.step_fail(f"Failed to add remote '{remote_name}'")
        fmt.line(f"  {fmt.C.DIM}The remote may already exist. Check: https://localhost:8443{fmt.C.RESET}")


def _phase_fleet_deploy(cfg, ctx, args=None):
    """Deploy service account + key to fleet hosts (all platform types)."""
    # Load per-device credentials (--device-credentials TOML)
    device_creds_file = getattr(args, "device_credentials", None) if args else None
    device_creds = _load_device_credentials(device_creds_file)
    if device_creds:
        fmt.step_ok(f"Device credentials loaded: {', '.join(sorted(device_creds.keys()))}")

    # Import hosts from file if --hosts-file provided
    hosts_file_arg = getattr(args, "hosts_file", None) if args else None
    if hosts_file_arg and os.path.isfile(hosts_file_arg) and not cfg.hosts:
        fmt.step_start(f"Importing fleet hosts from {hosts_file_arg}")
        shutil.copy2(hosts_file_arg, cfg.hosts_file)
        # Reload hosts
        from freq.core.config import load_hosts
        try:
            cfg.hosts = load_hosts(cfg.hosts_file)
            fmt.step_ok(f"Imported {len(cfg.hosts)} host(s) from {hosts_file_arg}")
        except Exception as e:
            fmt.step_fail(f"Failed to reload hosts: {e}")

    if not cfg.hosts:
        fmt.line(f"  {fmt.C.DIM}No hosts registered yet.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}How would you like to add fleet hosts?{fmt.C.RESET}")
        fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Auto-discover — scan your network for SSH-reachable hosts")
        fmt.line(f"    {fmt.C.BOLD}M{fmt.C.RESET}) Manual entry — add hosts one at a time")
        fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip — add hosts later with 'freq hosts add' or 'freq discover'")
        fmt.blank()

        choice = _input("Choice", "A").upper()

        if choice == "A":
            _discover_and_register(cfg, ctx)
            # After discovery, offer to add non-discoverable devices
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}Network scan can't find devices like pfSense, iDRAC, or managed switches.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}These need to be added manually.{fmt.C.RESET}")
            fmt.blank()
            if _confirm("Add non-discoverable devices (pfSense, iDRAC, switches)?"):
                fmt.blank()
                fmt.line(f"  {fmt.C.DIM}Enter hosts one at a time. Press Enter with empty IP to stop.{fmt.C.RESET}")
                fmt.blank()
                while True:
                    if not _register_host_interactive(cfg):
                        break
                    fmt.blank()
        elif choice == "M":
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}Enter hosts one at a time. Press Enter with empty IP to stop.{fmt.C.RESET}")
            fmt.blank()
            while True:
                if not _register_host_interactive(cfg):
                    break
                fmt.blank()
        else:
            fmt.step_warn("Skipping fleet registration — add hosts later with 'freq hosts add'")
            return

        if not cfg.hosts:
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}No hosts registered. Skipping fleet deployment.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Add hosts later with 'freq hosts add', then re-run init.{fmt.C.RESET}")
            return

        fmt.blank()
        fmt.line(f"  {fmt.C.GREEN}{len(cfg.hosts)} host(s) registered.{fmt.C.RESET} Proceeding to deployment...")
        fmt.blank()

    # Group hosts by auth category (using deployer registry)
    from freq.deployers import resolve_htype, PASSWORD_AUTH_CATEGORIES
    linux_hosts = [h for h in cfg.hosts if h.category == "server"]
    pfsense_hosts = [h for h in cfg.hosts if h.category == "firewall"]
    device_hosts = [h for h in cfg.hosts if h.category in ("bmc", "switch")]
    nas_hosts = [h for h in cfg.hosts if h.category == "nas"]
    # NAS hosts use server deployer (same SSH+useradd flow)
    linux_hosts.extend(nas_hosts)

    total = len(linux_hosts) + len(pfsense_hosts) + len(device_hosts)
    fmt.line(f"  {fmt.C.DIM}Fleet: {len(linux_hosts)} server, "
             f"{len(pfsense_hosts)} firewall, "
             f"{len(device_hosts)} device(s) — {total} total{fmt.C.RESET}")
    fmt.blank()

    ok = fail = 0

    # Check for CLI bootstrap credentials (--bootstrap-key, --bootstrap-user)
    bootstrap_key = getattr(args, "bootstrap_key", None) if args else None
    bootstrap_user = getattr(args, "bootstrap_user", None) if args else None
    has_bootstrap = bootstrap_key and os.path.isfile(bootstrap_key)

    # ── Linux-family hosts (linux, pve, docker, truenas) ──
    if linux_hosts:
        fmt.line(f"  {fmt.C.BOLD}Linux-family hosts ({len(linux_hosts)}){fmt.C.RESET}")
        fmt.blank()

        if has_bootstrap:
            # Bootstrap mode — skip interactive prompts
            linux_user = bootstrap_user or "root"
            linux_key = bootstrap_key
            linux_pass = ""
            fmt.step_ok(f"Using bootstrap auth: {linux_user} via {linux_key}")
            if linux_user != "root":
                fmt.line(f"  {fmt.C.DIM}Commands will be elevated via sudo on remote hosts.{fmt.C.RESET}")
                fmt.blank()
            for h in linux_hosts:
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                if _deploy_to_host_dispatch(h.ip, h.htype, ctx, linux_pass, linux_key, linux_user):
                    ok += 1
                else:
                    fail += 1
        else:
            # Interactive mode
            linux_user = _input("Deploy as user (root or sudo account)", "root")

            fmt.line(f"  {fmt.C.DIM}How to authenticate to Linux hosts as '{linux_user}'?{fmt.C.RESET}")
            fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Password (same for all)")
            fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
            fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
            fmt.blank()

            choice = _input("Choice", "A").upper()
            if choice != "S":
                linux_pass, linux_key = _get_auth_creds(choice, "Linux hosts")
                if linux_pass or linux_key:
                    if linux_user != "root":
                        fmt.line(f"  {fmt.C.DIM}Commands will be elevated via sudo on remote hosts.{fmt.C.RESET}")
                        fmt.blank()
                    for h in linux_hosts:
                        fmt.blank()
                        fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                        if _deploy_to_host_dispatch(h.ip, h.htype, ctx, linux_pass, linux_key, linux_user):
                            ok += 1
                        else:
                            fail += 1
            else:
                fmt.step_warn("Skipping Linux hosts")

    # ── pfSense hosts ──
    if pfsense_hosts:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}pfSense hosts ({len(pfsense_hosts)}){fmt.C.RESET}")
        fmt.blank()

        pf_creds = device_creds.get("pfsense")
        if pf_creds:
            # Device credentials mode — password auth from --device-credentials
            pf_user = pf_creds["user"]
            pf_pass = pf_creds["password"]
            pf_key = ""
            fmt.step_ok(f"Using device credentials for pfSense: {pf_user}")
            for h in pfsense_hosts:
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [pfsense]")
                if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                    ok += 1
                else:
                    fail += 1
        elif has_bootstrap:
            # Bootstrap mode for pfSense — use bootstrap key
            pf_user = bootstrap_user or "admin"
            pf_key = bootstrap_key
            pf_pass = ""
            fmt.step_ok(f"Using bootstrap auth for pfSense: {pf_user} via {pf_key}")
            for h in pfsense_hosts:
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [pfsense]")
                if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                    ok += 1
                else:
                    fail += 1
        else:
            fmt.line(f"  {fmt.C.DIM}How to authenticate to pfSense?{fmt.C.RESET}")
            fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Admin password")
            fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
            fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
            fmt.blank()

            choice = _input("Choice", "A").upper()
            if choice != "S":
                pf_user = _input("Auth user", "admin")
                pf_pass, pf_key = _get_auth_creds(choice, "pfSense")
                if pf_pass or pf_key:
                    for h in pfsense_hosts:
                        fmt.blank()
                        fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [pfsense]")
                        if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                            ok += 1
                        else:
                            fail += 1
            else:
                fmt.step_warn("Skipping pfSense hosts")

    # ── Device hosts (iDRAC, switch) ──
    if device_hosts:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Device hosts ({len(device_hosts)}){fmt.C.RESET}")
        fmt.blank()

        # Split devices by credential availability
        dev_with_creds = [h for h in device_hosts if h.htype in device_creds]
        dev_without_creds = [h for h in device_hosts if h.htype not in device_creds]

        # Deploy devices that have per-device credentials
        if dev_with_creds:
            for h in dev_with_creds:
                creds = device_creds[h.htype]
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                fmt.step_ok(f"Using device credentials: {creds['user']}")
                if _deploy_to_host_dispatch(h.ip, h.htype, ctx, creds["password"], "", creds["user"]):
                    ok += 1
                else:
                    fail += 1

        # Remaining devices — bootstrap key or interactive
        if dev_without_creds:
            if has_bootstrap:
                # Bootstrap mode for devices — use bootstrap key
                dev_user = bootstrap_user or "root"
                fmt.step_ok(f"Using bootstrap auth for devices: {dev_user} via {bootstrap_key}")
                for h in dev_without_creds:
                    fmt.blank()
                    fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                    if _deploy_to_host_dispatch(h.ip, h.htype, ctx, "", bootstrap_key, dev_user):
                        ok += 1
                    else:
                        fail += 1
            else:
                fmt.line(f"  {fmt.C.DIM}How to authenticate to iDRAC/switch?{fmt.C.RESET}")
                fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Admin password")
                fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
                fmt.blank()

                choice = _input("Choice", "A").upper()
                if choice != "S":
                    dev_user = _input("Auth user", "root")
                    rc, _, _ = _run(["which", "sshpass"])
                    if rc != 0:
                        fmt.step_fail("'sshpass' not installed — required for device auth")
                        from freq.core.packages import install_hint
                        fmt.line(f"  {fmt.C.DIM}Install with: {install_hint('sshpass')}{fmt.C.RESET}")
                    else:
                        dev_pass = getpass.getpass(f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for device admin ({dev_user}): ")
                        for h in dev_without_creds:
                            fmt.blank()
                            fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                            if _deploy_to_host_dispatch(h.ip, h.htype, ctx, dev_pass, "", dev_user):
                                ok += 1
                            else:
                                fail += 1
                else:
                    fmt.step_warn("Skipping device hosts")

    # Persist device (iDRAC/switch) password for ongoing SSH access
    if device_hosts and ok > 0 and ctx.get("svc_pass"):
        svc_home = os.path.expanduser("~" + ctx["svc_name"])
        pass_path = os.path.join(svc_home, ".ssh", "switch-pass")
        try:
            os.makedirs(os.path.dirname(pass_path), mode=0o700, exist_ok=True)
            with open(pass_path, "w") as f:
                f.write(ctx["svc_pass"])
            os.chmod(pass_path, 0o600)
            import pwd
            try:
                pw = pwd.getpwnam(ctx["svc_name"])
                os.chown(pass_path, pw.pw_uid, pw.pw_gid)
                os.chown(os.path.dirname(pass_path), pw.pw_uid, pw.pw_gid)
            except (KeyError, PermissionError):
                pass
            fmt.step_ok(f"Device password saved to {pass_path}")
        except OSError as e:
            fmt.step_warn(f"Could not save device password to {pass_path}: {e}")

    fmt.blank()
    fmt.line(f"  Fleet deployment: {fmt.C.GREEN}{ok} OK{fmt.C.RESET}, {fmt.C.RED}{fail} failed{fmt.C.RESET}")


def _get_auth_creds(choice, label):
    """Get auth credentials based on user's choice (A=password, B=key).
    Returns (password, key_path) — one will be empty string.
    """
    auth_pass = ""
    auth_key = ""
    if choice == "B":
        auth_key = _input("SSH key path", os.path.expanduser("~/.ssh/id_ed25519"))
        if not os.path.isfile(auth_key):
            fmt.step_warn(f"Key not found — falling back to password")
            auth_key = ""
    if not auth_key:
        rc, _, _ = _run(["which", "sshpass"])
        if rc != 0:
            fmt.step_fail("'sshpass' not installed — required for password-based SSH")
            from freq.core.packages import install_hint
            fmt.line(f"  {fmt.C.DIM}Install with: {install_hint('sshpass')}{fmt.C.RESET}")
            return "", ""
        auth_pass = getpass.getpass(f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Root password for {label}: ")
    return auth_pass, auth_key


def _init_ssh(ip, auth_pass, auth_key, auth_user):
    """Build an SSH helper for init-time auth (before FREQ keys are deployed).

    Returns a function _ssh(cmd, ..., as_root=False) -> (rc, stdout, stderr).
    When as_root=True and auth_user is not root, wraps the command in sudo
    using base64 encoding to avoid quoting issues with multi-line scripts.
    """
    ssh_opts = ["-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]

    def _ssh(cmd, extra_opts=None, timeout=DEFAULT_CMD_TIMEOUT, as_root=False):
        # Wrap in sudo if needed (non-root user running privileged commands)
        if as_root and auth_user != "root":
            # Base64-encode the script to avoid shell quoting nightmares
            cmd_b64 = base64.b64encode(cmd.encode()).decode()
            cmd = f"echo '{cmd_b64}' | base64 -d | sudo bash"
        base = ["ssh", "-n"] + ssh_opts
        if extra_opts:
            base.extend(extra_opts)
        if auth_key:
            full = base + ["-o", "BatchMode=yes", "-i", auth_key,
                           f"{auth_user}@{ip}", cmd]
            return _run(full, timeout=timeout)
        else:
            full = base + [f"{auth_user}@{ip}", cmd]
            return _ssh_with_pass(auth_pass, full, timeout=timeout)

    return _ssh


def _deploy_linux(ip, ctx, auth_pass, auth_key, auth_user, htype="linux"):
    """Deploy service account to a Linux-family host.

    Handles: linux, pve, docker, truenas.
    Detects Alpine vs glibc. Adds docker group for docker-type hosts.
    Returns True on success.
    """
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    pubkey = ctx["pubkey"]

    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({err[:60]})")
        return False
    fmt.step_ok("Connected")

    # Base64-encode password to prevent shell injection
    pass_b64 = base64.b64encode(svc_pass.encode()).decode()

    # Docker group line (only for docker-type hosts)
    docker_line = ""
    if htype == "docker":
        docker_line = f"getent group docker >/dev/null 2>&1 && usermod -aG docker '{svc_name}' || true"

    # Deploy script — Alpine-aware, with docker group support
    deploy = f"""set -e
# Create account (Alpine uses adduser, everything else uses useradd)
if ! id '{svc_name}' >/dev/null 2>&1; then
    if [ -f /etc/alpine-release ]; then
        adduser -D -s /bin/sh '{svc_name}' || {{ echo USERADD_FAIL; exit 1; }}
    else
        useradd -m -s /bin/bash '{svc_name}' || {{ echo USERADD_FAIL; exit 1; }}
    fi
fi
# Verify account exists
id '{svc_name}' >/dev/null 2>&1 || {{ echo ACCOUNT_MISSING; exit 1; }}
{docker_line}
# Password (base64-decoded to avoid shell injection)
_pass=$(echo '{pass_b64}' | base64 -d)
printf '%s:%s\\n' '{svc_name}' "$_pass" | chpasswd 2>/dev/null || echo CHPASSWD_FAIL
unset _pass
# Sudoers
echo '{svc_name} ALL=(ALL) NOPASSWD: ALL' > '/etc/sudoers.d/freq-{svc_name}'
chmod 440 '/etc/sudoers.d/freq-{svc_name}'
visudo -cf '/etc/sudoers.d/freq-{svc_name}' 2>/dev/null || {{ rm -f '/etc/sudoers.d/freq-{svc_name}'; echo SUDOERS_FAIL; exit 1; }}
# SSH key
svc_home=$(getent passwd '{svc_name}' | cut -d: -f6)
mkdir -p "$svc_home/.ssh"
chmod 700 "$svc_home/.ssh"
if [ -n '{pubkey}' ]; then
    grep -qF '{pubkey}' "$svc_home/.ssh/authorized_keys" 2>/dev/null || echo '{pubkey}' >> "$svc_home/.ssh/authorized_keys"
    chmod 600 "$svc_home/.ssh/authorized_keys"
    chown -R '{svc_name}:{svc_name}' "$svc_home/.ssh"
fi
echo DEPLOY_OK
"""
    rc, out, err = _ssh(deploy, as_root=True)
    if MARKER_USERADD_FAIL in out or "ACCOUNT_MISSING" in out:
        fmt.step_fail(f"Failed to create account '{svc_name}'")
        return False
    elif "SUDOERS_FAIL" in out:
        fmt.step_fail("Sudoers validation failed")
        return False
    elif MARKER_DEPLOY_OK not in out:
        fmt.step_fail(f"Deploy script failed ({err[:60]})")
        return False

    # Report chpasswd status
    if MARKER_CHPASSWD_FAIL in out:
        fmt.step_warn("Password set failed — account may be locked")
    else:
        fmt.step_ok("Account, password, sudo, SSH key deployed")

    # Verify FREQ key SSH access
    success = True
    if ctx.get("key_path") and os.path.isfile(ctx["key_path"]):
        rc2, _, _ = _run([
            "ssh", "-n", "-i", ctx["key_path"],
            "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{svc_name}@{ip}", "echo OK",
        ])
        if rc2 == 0:
            fmt.step_ok(f"Verified: FREQ key SSH as {svc_name}")
        else:
            fmt.step_fail(f"FREQ key login FAILED as {svc_name} — check sshd + authorized_keys")
            success = False

        # Verify sudo works
        if rc2 == 0:
            rc3, _, _ = _run([
                "ssh", "-n", "-i", ctx["key_path"],
                "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{svc_name}@{ip}", "sudo -n true",
            ])
            if rc3 == 0:
                fmt.step_ok(f"Verified: NOPASSWD sudo works as {svc_name}")
            else:
                fmt.step_fail(f"SUDO FAILED — {svc_name} cannot sudo on {ip}")
                success = False

    return success


def _deploy_pfsense(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to pfSense (FreeBSD).

    Uses pw useradd. No sudo (pfSense admin model). ed25519 key.
    Returns True on success.
    """
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    pubkey = ctx["pubkey"]

    # pfSense: admin IS root (UID 0). No sudo available on FreeBSD/pfSense.
    # Auth user must be root or admin for user creation to work.
    if auth_user not in ("root", "admin"):
        fmt.step_warn(f"pfSense auth as '{auth_user}' — may lack privilege (root/admin required for pw useradd)")

    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({err[:60]})")
        return False
    fmt.step_ok("Connected")

    # Base64-encode password
    pass_b64 = base64.b64encode(svc_pass.encode()).decode()

    # FreeBSD deploy script — pw useradd, no sudoers
    deploy = f"""
# Create account (FreeBSD)
if ! pw usershow '{svc_name}' >/dev/null 2>&1; then
    pw useradd -n '{svc_name}' -m -s /bin/sh -w no || {{ echo USERADD_FAIL; exit 1; }}
fi
pw usershow '{svc_name}' >/dev/null 2>&1 || {{ echo ACCOUNT_MISSING; exit 1; }}
# Password (pw reads from stdin with -h 0)
echo '{pass_b64}' | base64 -d | pw usermod '{svc_name}' -h 0 || echo CHPASSWD_FAIL
# SSH key
svc_home=$(pw usershow '{svc_name}' | cut -d: -f9)
mkdir -p "$svc_home/.ssh"
chmod 700 "$svc_home/.ssh"
if [ -n '{pubkey}' ]; then
    grep -qF '{pubkey}' "$svc_home/.ssh/authorized_keys" 2>/dev/null || echo '{pubkey}' >> "$svc_home/.ssh/authorized_keys"
    chmod 600 "$svc_home/.ssh/authorized_keys"
    chown -R '{svc_name}' "$svc_home/.ssh"
fi
echo DEPLOY_OK
"""
    rc, out, err = _ssh(deploy)  # No as_root — pfSense admin IS root, no sudo
    if MARKER_USERADD_FAIL in out or "ACCOUNT_MISSING" in out:
        fmt.step_fail(f"Failed to create account '{svc_name}'")
        return False
    elif MARKER_DEPLOY_OK not in out:
        fmt.step_fail(f"Deploy script failed ({err[:60]})")
        return False

    if MARKER_CHPASSWD_FAIL in out:
        fmt.step_warn("Password set failed on pfSense")
    else:
        fmt.step_ok("Account, password, SSH key deployed (no sudo — pfSense)")

    # Verify FREQ key SSH access (no sudo on pfSense)
    success = True
    if ctx.get("key_path") and os.path.isfile(ctx["key_path"]):
        rc2, _, _ = _run([
            "ssh", "-n", "-i", ctx["key_path"],
            "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{svc_name}@{ip}", "echo OK",
        ])
        if rc2 == 0:
            fmt.step_ok(f"Verified: FREQ key SSH as {svc_name}")
        else:
            fmt.step_fail(f"FREQ key login FAILED as {svc_name}")
            success = False

    return success


def _deploy_idrac(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to Dell iDRAC.

    Uses racadm commands. RSA key only. Password auth for initial connect.
    Returns True on success.
    """
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    rsa_pubkey = ctx.get("rsa_pubkey", "")

    if not rsa_pubkey:
        fmt.step_fail("No RSA public key — iDRAC requires RSA (not ed25519)")
        return False

    # iDRAC requires legacy ciphers
    extra_opts = PLATFORM_SSH.get("idrac", {}).get("extra_opts", [])
    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity with legacy ciphers
    rc, out, err = _ssh("racadm getsysinfo", extra_opts=extra_opts)
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({err[:60]})")
        return False
    fmt.step_ok("Connected to iDRAC")

    # Find an empty user slot (slots 3-16, 1-2 are reserved)
    rc, out, err = _ssh(_gen_idrac_slot_check(), extra_opts=extra_opts)
    if rc != 0:
        fmt.step_fail(f"Cannot query iDRAC user slots ({err[:60]})")
        return False

    # Parse slots — find first empty or matching
    target_slot, existing_slot = _parse_idrac_slots(out, svc_name)

    if existing_slot:
        fmt.step_ok(f"Account '{svc_name}' already in slot {existing_slot}")
        target_slot = existing_slot
    elif target_slot:
        fmt.step_ok(f"Using empty slot {target_slot}")
    else:
        fmt.step_fail("No empty iDRAC user slots (3-16 all occupied)")
        return False

    # Create/update user in target slot
    setup_cmds = [
        f"racadm set iDRAC.Users.{target_slot}.UserName {svc_name}",
        f"racadm set iDRAC.Users.{target_slot}.Password {svc_pass}",
        f"racadm set iDRAC.Users.{target_slot}.Privilege 0x1ff",
        f"racadm set iDRAC.Users.{target_slot}.Enable 1",
        f"racadm set iDRAC.Users.{target_slot}.IpmiLanPrivilege 4",
    ]
    setup_script = " && ".join(setup_cmds) + " && echo SETUP_OK"
    rc, out, err = _ssh(setup_script, extra_opts=extra_opts, timeout=IDRAC_SETUP_TIMEOUT)

    if MARKER_SETUP_OK not in out:
        fmt.step_fail(f"iDRAC user setup failed ({(err or out).strip()[:80]})")
        return False
    fmt.step_ok(f"iDRAC user '{svc_name}' configured (slot {target_slot})")

    # Deploy RSA public key
    rc, out, err = _ssh(
        f"racadm sshpkauth -i {target_slot} -k 1 -t \"{rsa_pubkey}\"",
        extra_opts=extra_opts, timeout=30,
    )
    if rc != 0:
        fmt.step_fail(f"RSA key upload failed ({(err or out).strip()[:60]})")
        fmt.step_warn("iDRAC user created but key-based SSH won't work — password auth only")
        return False

    # Verify the key was actually stored
    rc2, out2, _ = _ssh(
        f"racadm sshpkauth -v -i {target_slot} -k 1",
        extra_opts=extra_opts, timeout=IDRAC_VERIFY_TIMEOUT,
    )
    if rc2 == 0 and out2.strip():
        fmt.step_ok("RSA public key deployed and verified on iDRAC")
    else:
        fmt.step_warn("RSA key uploaded but verification query failed — check manually")

    return True


def _deploy_switch(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to Cisco IOS switch.

    Uses IOS config commands. RSA key only. Password auth for initial connect.
    Returns True on success.
    """
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    rsa_pubkey = ctx.get("rsa_pubkey", "")

    if not rsa_pubkey:
        fmt.step_fail("No RSA public key — switch requires RSA (not ed25519)")
        return False

    # Switch requires legacy ciphers
    extra_opts = PLATFORM_SSH.get("switch", {}).get("extra_opts", [])
    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("show version | include uptime", extra_opts=extra_opts)
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({err[:60]})")
        return False
    fmt.step_ok("Connected to switch")

    # Build IOS config commands — create user + deploy RSA public key
    # RSA public key base64 data split into 72-char lines (PEM width).
    # IOS key-string chokes on 254-char lines — 72 works reliably.
    rsa_key_data = rsa_pubkey.split(" ")[1] if " " in rsa_pubkey else rsa_pubkey
    key_lines = [rsa_key_data[i:i+IOS_KEY_LINE_WIDTH] for i in range(0, len(rsa_key_data), IOS_KEY_LINE_WIDTH)]

    ios_cmds = [
        "configure terminal",
        f"username {svc_name} privilege 15 secret {svc_pass}",
        "ip ssh pubkey-chain",
        f"username {svc_name}",
        "key-string",
    ]
    # Key data lines — NO leading spaces (IOS includes them in key data)
    for kl in key_lines:
        ios_cmds.append(kl)
    ios_cmds.extend([
        "exit",           # exit key-string → username
        "exit",           # exit username → pubkey-chain
        "exit",           # exit pubkey-chain → config
        "exit",           # exit config → exec mode
        "write memory",   # save config (exec mode only)
    ])

    # Pipe IOS commands via stdin — IOS requires interactive-style input
    # for config mode (configure terminal). SSH exec args don't work for
    # multi-command config sessions. Uses ssh -T (no pseudo-tty).
    ios_cmds.append("exit")  # exit exec mode to close session cleanly
    ios_script = "\n".join(ios_cmds) + "\n"

    ssh_cmd = [
        "ssh", "-T",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if extra_opts:
        ssh_cmd.extend(extra_opts)
    ssh_cmd.append(f"{auth_user}@{ip}")

    if auth_pass:
        rc, out, err = _ssh_with_pass(auth_pass, ssh_cmd, timeout=30,
                                       input_text=ios_script)
    elif auth_key:
        ssh_cmd.extend(["-o", "BatchMode=yes", "-i", auth_key])
        rc, out, err = _run_with_input(ssh_cmd, ios_script, timeout=30)
    else:
        rc, out, err = _run_with_input(ssh_cmd, ios_script, timeout=30)

    # IOS doesn't give clean exit codes — check for specific error indicators.
    # Generic "error" matching is too broad — IOS echoes "error" in normal output.
    out_lower = (out or "").lower()
    ios_errors = [
        "% invalid input detected",     # bad command syntax
        "% incomplete command",          # missing args
        "% ambiguous command",           # ambiguous abbreviation
        "% authorization failed",        # AAA rejection
        "% authentication failed",       # login failure
        "% bad ip address",              # invalid IP
        "% invalid username",            # user creation failure
        "%ssh-4-badpkauth",              # key auth failure (syslog)
    ]
    key_warnings = [
        "%ssh: failed to decode",        # bad key data (base64/format)
        "failed to decode the key",
    ]

    # Hard errors — config definitely failed
    for pat in ios_errors:
        if pat in out_lower:
            fmt.step_fail(f"IOS config failed: {pat.strip('% ')} ({out.strip()[:80]})")
            return False

    # Key decode warnings — user created but key won't work
    key_warn = False
    for pat in key_warnings:
        if pat in out_lower:
            fmt.step_warn(f"IOS key import issue: {pat.strip('% ')}")
            key_warn = True

    # Check for write memory success
    if "[OK]" in out or "[ok]" in out_lower:
        if key_warn:
            fmt.step_warn(f"Switch user '{svc_name}' created, config saved — but SSH key may not work")
        else:
            fmt.step_ok(f"Switch user '{svc_name}' + RSA key configured, config saved")
    else:
        fmt.step_ok(f"Switch user '{svc_name}' configured (verify write memory)")

    return True


def _deploy_to_host_dispatch(ip, htype, ctx, auth_pass, auth_key, auth_user):
    """Route to platform-specific deployer based on host type.

    Supports both legacy htypes ('pfsense') and category:vendor ('firewall:pfsense').
    Returns True on success.
    """
    from freq.deployers import resolve_htype, get_deployer

    category, vendor = resolve_htype(htype)
    deployer = get_deployer(category, vendor)
    if deployer:
        # Server deployers accept htype kwarg for docker group handling
        if category == "server":
            return deployer.deploy(ip, ctx, auth_pass, auth_key, auth_user, htype=htype)
        return deployer.deploy(ip, ctx, auth_pass, auth_key, auth_user)

    # Fallback for unknown types — try linux deployer (best effort)
    fmt.step_warn(f"No deployer for '{htype}' ({category}:{vendor}) — trying generic Linux")
    return _deploy_linux(ip, ctx, auth_pass, auth_key, auth_user, htype=htype)


# ═══════════════════════════════════════════════════════════════════
# UNINSTALL — per-platform removal
# ═══════════════════════════════════════════════════════════════════

def _uninstall_ssh(ip, svc_name, key_path, extra_opts=None):
    """Build an SSH runner for uninstall — auths as the FREQ service account."""
    def _ssh(cmd, timeout=DEFAULT_CMD_TIMEOUT):
        ssh_cmd = [
            "ssh", "-n", "-i", key_path,
            "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if extra_opts:
            ssh_cmd.extend(extra_opts)
        ssh_cmd.extend([f"{svc_name}@{ip}", cmd])
        return _run(ssh_cmd, timeout=timeout)
    return _ssh


def _remove_linux(ip, svc_name, key_path):
    """Remove FREQ service account from a Linux-family host.

    Removes: sudoers, docker group membership, user account + home.
    Uses two SSH calls: first cleans up privileges, second schedules account
    deletion via a detached process (since we're deleting our own login user).
    Returns (success, error_info).
    """
    _ssh = _uninstall_ssh(ip, svc_name, key_path)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        return False, err

    # Step 1: Remove sudoers + docker group (while we still have sudo)
    rc, out, err = _ssh(
        f"sudo bash -c '"
        f"rm -f /etc/sudoers.d/freq-{svc_name}; "
        f"gpasswd -d {svc_name} docker 2>/dev/null || true; "
        f"echo CLEAN_OK'",
        timeout=QUICK_CHECK_TIMEOUT,
    )
    if MARKER_CLEAN_OK not in (out or ""):
        return False, f"privilege cleanup failed: {(err or out).strip()[:80]}"

    # Step 2: Schedule account deletion via detached process
    # We're logged in as svc_name and deleting ourselves, so this must
    # run async after our SSH session closes.
    _ssh(
        f"sudo nohup bash -c '"
        f"sleep 1; "
        f"pkill -u {svc_name} 2>/dev/null || true; "
        f"userdel -r {svc_name} 2>/dev/null || userdel {svc_name} 2>/dev/null || true"
        f"' >/dev/null 2>&1 &",
        timeout=PING_TIMEOUT,
    )

    return True, ""


def _remove_pfsense(ip, svc_name, key_path):
    """Remove FREQ service account from pfSense (FreeBSD).

    Removes: user account + home directory.
    Returns (success, error).
    """
    _ssh = _uninstall_ssh(ip, svc_name, key_path)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        return False, err

    # pfSense: no sudo, but FREQ account can't delete itself directly.
    # We need to check if this is run as admin/root or if the account has
    # enough privilege. On pfSense, only root/admin can pw userdel.
    # The FREQ account does NOT have sudo on pfSense by design.
    # This means we need root/admin creds to remove from pfSense.
    # For now, just remove the SSH key (which the user owns).
    _ssh("rm -rf ~/.ssh/authorized_keys 2>/dev/null; echo KEY_REMOVED")

    return True, "key_only"


def _remove_idrac(ip, svc_name, key_path):
    """Remove FREQ service account from iDRAC.

    Finds the user's slot, disables it, clears name + key.
    Returns (success, error).
    """
    extra_opts = PLATFORM_SSH.get("idrac", {}).get("extra_opts", [])
    rsa_key = key_path
    _ssh = _uninstall_ssh(ip, svc_name, rsa_key, extra_opts=extra_opts)

    # Test connectivity
    rc, out, err = _ssh("racadm getsysinfo")
    if rc != 0:
        return False, err

    # Find the user's slot
    rc, out, err = _ssh(_gen_idrac_slot_check())
    if rc != 0:
        return False, f"cannot query slots: {err[:60]}"

    _, target_slot = _parse_idrac_slots(out, svc_name)
    # In removal, we want the existing slot (not the empty one)
    # _parse_idrac_slots returns (empty_slot, existing_slot)

    if not target_slot:
        return True, "not_found"  # Already gone

    # Disable the slot, clear username, remove SSH key
    remove_cmds = [
        f"racadm set iDRAC.Users.{target_slot}.Enable 0",
        f"racadm set iDRAC.Users.{target_slot}.UserName \"\"",
        f"racadm sshpkauth -i {target_slot} -k 1 -t \"\"",
    ]
    remove_script = " && ".join(remove_cmds) + " && echo REMOVE_OK"
    rc, out, err = _ssh(remove_script, timeout=30)

    if "REMOVE_OK" in out:
        return True, ""
    return False, f"removal failed: {(err or out).strip()[:80]}"


def _remove_switch(ip, svc_name, key_path):
    """Remove FREQ service account from Cisco IOS switch.

    Removes: username + pubkey-chain entry, writes config.
    Returns (success, error).
    """
    extra_opts = PLATFORM_SSH.get("switch", {}).get("extra_opts", [])
    rsa_key = key_path
    _ssh = _uninstall_ssh(ip, svc_name, rsa_key, extra_opts=extra_opts)

    # Test connectivity
    rc, out, err = _ssh("show version | include uptime")
    if rc != 0:
        return False, err

    # IOS removal commands
    ios_cmds = [
        "configure terminal",
        f"no username {svc_name}",
        "ip ssh pubkey-chain",
        f"  no username {svc_name}",
        "  exit",
        "exit",
        "write memory",
    ]
    ios_script = "\n".join(ios_cmds)
    rc, out, err = _ssh(ios_script, timeout=30)

    out_lower = (out or "").lower()
    if "invalid input" in out_lower:
        return False, f"IOS error: {out.strip()[:80]}"

    return True, ""


def _remove_from_host_dispatch(ip, htype, svc_name, key_path, rsa_key_path):
    """Route to platform-specific remover. Returns (success, error_info)."""
    from freq.deployers import resolve_htype, get_deployer, RSA_REQUIRED_CATEGORIES

    category, vendor = resolve_htype(htype)
    deployer = get_deployer(category, vendor)
    if deployer:
        use_key = rsa_key_path if category in RSA_REQUIRED_CATEGORIES else key_path
        return deployer.remove(ip, svc_name, use_key, rsa_key_path=rsa_key_path)

    return False, f"no deployer for {htype} ({category}:{vendor})"


# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Admin Account Setup
# ═══════════════════════════════════════════════════════════════════

def _phase_admin_setup(cfg, ctx):
    """Configure RBAC roles."""
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")

    # Ensure file exists
    if not os.path.isfile(roles_file):
        open(roles_file, "a").close()

    # Current user
    current_user = os.environ.get("SUDO_USER", os.environ.get("USER", "root"))
    fmt.line(f"  {fmt.C.DIM}Current user: {fmt.C.BOLD}{current_user}{fmt.C.RESET}")
    fmt.blank()

    with open(roles_file) as f:
        roles_data = f.read()

    # Add current user as admin
    if f"{current_user}:" in roles_data:
        fmt.step_ok(f"{current_user} already in roles.conf")
    else:
        with open(roles_file, "a") as f:
            f.write(f"{current_user}:admin\n")
        fmt.step_ok(f"Added {current_user} as admin")

    # Add service account as admin
    svc_name = ctx["svc_name"]
    with open(roles_file) as f:
        roles_data = f.read()
    if f"{svc_name}:" not in roles_data:
        with open(roles_file, "a") as f:
            f.write(f"{svc_name}:admin\n")
        fmt.step_ok(f"Added {svc_name} as admin")

    # Offer additional accounts
    fmt.blank()
    if _confirm("Create additional admin or operator accounts?"):
        while True:
            fmt.blank()
            username = _input("Username (Enter to finish)")
            if not username:
                break
            if not _validate_username(username):
                fmt.step_fail(f"Invalid username '{username}' — must be lowercase, start with letter/underscore")
                continue
            fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) admin")
            fmt.line(f"    {fmt.C.BOLD}O{fmt.C.RESET}) operator")
            role_choice = _input("Role", "O").upper()
            role = "admin" if role_choice == "A" else "operator"

            with open(roles_file) as f:
                roles_data = f.read()
            if f"{username}:" in roles_data:
                fmt.line(f"  {fmt.C.DIM}{username} already in roles.conf{fmt.C.RESET}")
            else:
                with open(roles_file, "a") as f:
                    f.write(f"{username}:{role}\n")
                fmt.step_ok(f"Added {username} as {role}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 8: Verification
# ═══════════════════════════════════════════════════════════════════

def _is_skip_error(err):
    """Check if SSH error is a skip-worthy condition (not a real failure)."""
    err_l = err.lower()
    return any(s in err_l for s in [
        "no route to host", "connection timed out", "connection refused",
        "permission denied", "authentication", "host key verification failed",
    ])


def _skip_reason(err):
    """Return a human-readable reason for skipping a host."""
    err_l = err.lower()
    if "no route to host" in err_l or "connection timed out" in err_l or "connection refused" in err_l:
        return "unreachable"
    if "permission denied" in err_l or "authentication" in err_l:
        return "auth failed"
    if "host key verification" in err_l:
        return "host key mismatch"
    return "SSH error"


def _verify_host(ip, htype, svc_name, key_path, rsa_key_path):
    """Platform-aware host verification. Returns (success, error_stderr)."""
    # Select key and command based on platform
    if htype in ("linux", "pve", "docker", "truenas"):
        key = key_path
        verify_cmd = "sudo -n true"
        extra_opts = []
    elif htype == "pfsense":
        key = key_path
        verify_cmd = "echo OK"
        extra_opts = []
    elif htype == "idrac":
        key = rsa_key_path
        verify_cmd = "racadm getsysinfo -s"
        extra_opts = PLATFORM_SSH.get("idrac", {}).get("extra_opts", [])
    elif htype == "switch":
        key = rsa_key_path
        verify_cmd = "show version | include uptime"
        extra_opts = PLATFORM_SSH.get("switch", {}).get("extra_opts", [])
    else:
        return False, f"unknown htype: {htype}"

    if not key or not os.path.isfile(key):
        return False, f"key not found: {key}"

    ssh_cmd = [
        "ssh", "-n", "-i", key,
        "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
    ] + extra_opts + [f"{svc_name}@{ip}", verify_cmd]

    rc, out, err = _run(ssh_cmd, timeout=VERIFY_TIMEOUT)
    # iDRAC has a 2-session SSH limit — retry once after a short wait
    if rc != 0 and htype in ("idrac", "switch") and "no more sessions" in (out + err).lower():
        time.sleep(5)
        rc, out, err = _run(ssh_cmd, timeout=VERIFY_TIMEOUT)
    return rc == 0, err


def _phase_verify(cfg, ctx):
    """Verify all init steps completed. Returns True if all pass."""
    svc_name = ctx["svc_name"]
    passes = 0
    fails = 0

    def _check(label, condition):
        nonlocal passes, fails
        if condition:
            fmt.step_ok(label)
            passes += 1
        else:
            fmt.step_fail(label)
            fails += 1

    # Service account
    rc, _, _ = _run(["id", svc_name])
    _check("Service account exists locally", rc == 0)

    # SSH keys
    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")
    _check("FREQ ed25519 key exists (modern hosts)", os.path.isfile(key_file))
    _check("FREQ RSA key exists (iDRAC + switch)", os.path.isfile(rsa_file))

    # Vault
    _check("Vault exists", os.path.isfile(cfg.vault_file))

    # Roles
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    _check("roles.conf readable", os.path.isfile(roles_file))

    # Config
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    _check("freq.toml exists", os.path.isfile(toml_path))

    # Log dir
    log_dir = os.path.dirname(cfg.log_file)
    _check("Log dir writable", os.access(log_dir, os.W_OK))

    # Hosts
    if cfg.hosts:
        _check(f"hosts.conf: {len(cfg.hosts)} hosts", True)
    else:
        fmt.step_warn("hosts.conf is empty — use 'freq hosts add' or 'freq discover'")

    # Timezone
    tz = "unknown"
    try:
        rc, out, _ = _run(["timedatectl", "show", "--property=Timezone", "--value"])
        if rc == 0:
            tz = out.strip()
    except (OSError, FileNotFoundError):
        pass  # timedatectl may not be available on all systems
    fmt.line(f"  {fmt.C.GREEN}✔{fmt.C.RESET} Timezone: {tz}")

    # PVE connectivity
    warns = 0
    if cfg.pve_nodes and os.path.isfile(key_file):
        for ip in cfg.pve_nodes:
            ok, err = _verify_host(ip, "pve", svc_name, key_file, rsa_file)
            if ok:
                _check(f"PVE {ip}: SSH + sudo as {svc_name}", True)
            elif _is_skip_error(err):
                fmt.step_warn(f"PVE {ip}: {_skip_reason(err)} (skipped)")
                warns += 1
            else:
                _check(f"PVE {ip}: SSH + sudo as {svc_name}", False)

    # Fleet host connectivity — ALL platform types
    if cfg.hosts:
        pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
        fleet_hosts = [h for h in cfg.hosts if h.ip not in pve_set]

        for h in fleet_hosts:
            # Platform-appropriate label
            if h.htype in ("linux", "pve", "docker", "truenas"):
                check_label = f"Fleet {h.label} ({h.ip}): SSH + sudo as {svc_name}"
            elif h.htype == "pfsense":
                check_label = f"Fleet {h.label} ({h.ip}): SSH as {svc_name} (no sudo)"
            elif h.htype in ("idrac", "switch"):
                check_label = f"Fleet {h.label} ({h.ip}): SSH as {svc_name} [{h.htype}]"
            else:
                fmt.step_warn(f"Fleet {h.label} ({h.ip}): unknown type '{h.htype}' (skipped)")
                warns += 1
                continue

            ok, err = _verify_host(h.ip, h.htype, svc_name, key_file, rsa_file)
            if ok:
                _check(check_label, True)
            elif _is_skip_error(err):
                fmt.step_warn(f"Fleet {h.label} ({h.ip}): {_skip_reason(err)} (skipped)")
                warns += 1
            else:
                _check(check_label, False)

    fmt.blank()
    summary = f"  Verification: {fmt.C.GREEN}{passes} pass{fmt.C.RESET}, {fmt.C.RED}{fails} fail{fmt.C.RESET}"
    if warns:
        summary += f", {fmt.C.YELLOW}{warns} unreachable{fmt.C.RESET}"
    fmt.line(summary)

    # Mark initialized — unreachable hosts are warnings, not failures
    if fails == 0:
        marker = f"PVE FREQ {cfg.version} — initialized {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        with open(INIT_MARKER, "w") as f:
            f.write(marker + "\n")
        fmt.step_ok(f"Marked initialized: {INIT_MARKER}")
        if warns:
            fmt.line(f"  {fmt.C.DIM}Re-run 'freq init' when unreachable hosts come online.{fmt.C.RESET}")
        return True
    else:
        fmt.step_fail(f"NOT initialized ({fails} failures — fix and re-run 'freq init')")
        return False


# ═══════════════════════════════════════════════════════════════════
# PHASE 9: Summary
# ═══════════════════════════════════════════════════════════════════

def _phase_summary(cfg, ctx, verified, pack=None):
    """Print summary and next steps."""
    svc_name = ctx["svc_name"]
    ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_key = os.path.join(cfg.key_dir, "freq_id_rsa")

    if verified:
        fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}FREQ {cfg.version} is ready.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.YELLOW}FREQ {cfg.version} is partially configured.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}What was configured:{fmt.C.RESET}")
    fmt.line(f"    Service account: {fmt.C.BOLD}{svc_name}{fmt.C.RESET}")
    fmt.line(f"    SSH key (modern):  {ed_key}")
    fmt.line(f"    SSH key (legacy):  {rsa_key}")
    fmt.line(f"    Vault: {cfg.vault_file}")
    fmt.line(f"    SSH mode: sudo (via {svc_name})")

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Next steps:{fmt.C.RESET}")
    fmt.line(f"    freq hosts list      — see registered hosts")
    fmt.line(f"    freq discover        — find unregistered VMs")
    fmt.line(f"    freq hosts add       — add your first host")
    fmt.line(f"    freq doctor          — verify FREQ is healthy")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Break-glass access: su - {svc_name}{fmt.C.RESET}")
    fmt.blank()

    # Celebrate
    if pack:
        from freq.core.personality import celebrate
        msg = celebrate(pack)
        if msg:
            fmt.line(f"  {fmt.C.DIM}{msg}{fmt.C.RESET}")

    fmt.footer()


# ═══════════════════════════════════════════════════════════════════
# --check mode
# ═══════════════════════════════════════════════════════════════════

def _scan_fleet(cfg):
    """Test freq-admin SSH to all hosts. Returns (ok_list, fail_list, unreachable_list).

    Each entry is a dict: {host, ip, htype, error}.
    Shared by --check and --fix.
    """
    import concurrent.futures

    svc_name = cfg.ssh_service_account
    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")

    pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
    all_hosts = []

    # PVE nodes
    for ip in (cfg.pve_nodes or []):
        all_hosts.append({"label": ip, "ip": ip, "htype": "pve"})

    # Fleet hosts (skip PVE nodes already covered)
    for h in cfg.hosts:
        if h.ip not in pve_set:
            all_hosts.append({"label": h.label, "ip": h.ip, "htype": h.htype})

    ok_list = []
    fail_list = []
    unreachable_list = []

    def _test_one(entry):
        ok, err = _verify_host(entry["ip"], entry["htype"], svc_name, key_file, rsa_file)
        return entry, ok, err

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_test_one, h) for h in all_hosts]
        for f in concurrent.futures.as_completed(futures):
            entry, ok, err = f.result()
            entry["error"] = err if not ok else ""
            if ok:
                ok_list.append(entry)
            elif _is_skip_error(err):
                unreachable_list.append(entry)
            else:
                fail_list.append(entry)

    return ok_list, fail_list, unreachable_list


def _init_check(cfg):
    """Validate init state — local files + remote host SSH."""
    fmt.header("Init Check")
    fmt.blank()

    svc_name = cfg.ssh_service_account
    passes = fails = warns = 0

    def _chk(label, status):
        nonlocal passes, fails, warns
        if status == "pass":
            fmt.step_ok(label)
            passes += 1
        elif status == "fail":
            fmt.step_fail(label)
            fails += 1
        else:
            fmt.step_warn(label)
            warns += 1

    # ── Local checks ──
    fmt.line(f"  {fmt.C.BOLD}Local State{fmt.C.RESET}")
    fmt.blank()

    marker = os.path.join(cfg.conf_dir, ".initialized")
    if os.path.isfile(marker):
        with open(marker) as f:
            _chk(f"Initialized: {f.read().strip()}", "pass")
    else:
        _chk("Not initialized (.initialized file missing)", "warn")

    rc, _, _ = _run(["id", svc_name])
    _chk(f"Service account '{svc_name}' exists", "pass" if rc == 0 else "fail")

    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")
    _chk("SSH ed25519 key (modern hosts)", "pass" if os.path.isfile(key_file) else "fail")
    _chk("SSH RSA key (iDRAC + switch)", "pass" if os.path.isfile(rsa_file) else "warn")

    _chk("Vault file exists", "pass" if os.path.isfile(cfg.vault_file) else "fail")

    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    _chk("freq.toml exists", "pass" if os.path.isfile(toml_path) else "fail")

    if cfg.hosts:
        _chk(f"hosts.conf: {len(cfg.hosts)} hosts", "pass")
    else:
        _chk("hosts.conf is empty", "warn")

    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    _chk("roles.conf exists", "pass" if os.path.isfile(roles_file) else "warn")

    # ── Remote fleet verification ──
    if cfg.hosts or cfg.pve_nodes:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Fleet Verification{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Testing SSH as '{svc_name}' to all registered hosts...{fmt.C.RESET}")
        fmt.blank()

        ok_list, fail_list, unreachable_list = _scan_fleet(cfg)

        for h in sorted(ok_list, key=lambda x: x["label"]):
            _chk(f"{h['label']} ({h['ip']}) [{h['htype']}]", "pass")
        for h in sorted(fail_list, key=lambda x: x["label"]):
            err_short = h["error"][:60] if h["error"] else "auth failed"
            _chk(f"{h['label']} ({h['ip']}) [{h['htype']}]: {err_short}", "fail")
        for h in sorted(unreachable_list, key=lambda x: x["label"]):
            _chk(f"{h['label']} ({h['ip']}) [{h['htype']}]: {_skip_reason(h['error'])}", "warn")

    fmt.blank()
    summary = f"  {fmt.C.GREEN}{passes} pass{fmt.C.RESET}"
    if fails:
        summary += f", {fmt.C.RED}{fails} fail{fmt.C.RESET}"
    if warns:
        summary += f", {fmt.C.YELLOW}{warns} warn{fmt.C.RESET}"
    fmt.line(summary)

    if cfg.hosts or cfg.pve_nodes:
        if fail_list:
            fmt.blank()
            fmt.line(f"  {fmt.C.DIM}Run 'freq init --fix' to repair broken hosts.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()

    return 0 if fails == 0 else 1


# ═══════════════════════════════════════════════════════════════════
# --fix mode
# ═══════════════════════════════════════════════════════════════════

def _init_fix(cfg, args):
    """Scan fleet, find broken hosts, redeploy freq-admin.

    Uses bootstrap auth (password or existing key) to reach hosts where
    freq-admin is broken/missing, then deploys using the same machinery
    as the full init wizard.
    """
    fmt.header("Init Fix — Repair Broken Hosts")
    fmt.blank()

    svc_name = cfg.ssh_service_account
    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")

    # Need the FREQ keys to exist
    if not os.path.isfile(key_file):
        fmt.step_fail("FREQ ed25519 key not found — run 'freq init' first")
        return 1

    # Build deploy context (same as full init)
    ed_pub = key_file + ".pub"
    rsa_pub = rsa_file + ".pub"
    pubkey = ""
    rsa_pubkey = ""
    if os.path.isfile(ed_pub):
        with open(ed_pub) as f:
            pubkey = f.read().strip()
    if os.path.isfile(rsa_pub):
        with open(rsa_pub) as f:
            rsa_pubkey = f.read().strip()
    ctx = {
        "svc_name": svc_name,
        "svc_pass": "",  # Will prompt if needed
        "key_path": key_file,
        "pubkey": pubkey,
        "rsa_key_path": rsa_file,
        "rsa_pubkey": rsa_pubkey,
    }

    if not ctx["pubkey"]:
        fmt.step_fail("FREQ ed25519 public key not found")
        return 1

    # Phase 1: Scan
    fmt.line(f"  {fmt.C.BOLD}Phase 1: Scanning fleet...{fmt.C.RESET}")
    fmt.blank()

    ok_list, fail_list, unreachable_list = _scan_fleet(cfg)

    fmt.line(f"  {fmt.C.GREEN}{len(ok_list)} OK{fmt.C.RESET}, "
             f"{fmt.C.RED}{len(fail_list)} broken{fmt.C.RESET}, "
             f"{fmt.C.YELLOW}{len(unreachable_list)} unreachable{fmt.C.RESET}")
    fmt.blank()

    if not fail_list:
        fmt.step_ok("All reachable hosts are healthy — nothing to fix")
        fmt.blank()
        fmt.footer()
        return 0

    # Show broken hosts
    fmt.line(f"  {fmt.C.BOLD}Broken hosts:{fmt.C.RESET}")
    for h in fail_list:
        err_short = h["error"][:60] if h["error"] else "auth failed"
        fmt.line(f"    {fmt.C.RED}✗{fmt.C.RESET} {h['label']} ({h['ip']}) [{h['htype']}] — {err_short}")
    fmt.blank()

    # Group by platform type for auth prompts
    linux_broken = [h for h in fail_list if h["htype"] in ("linux", "pve", "docker", "truenas")]
    pfsense_broken = [h for h in fail_list if h["htype"] == "pfsense"]
    device_broken = [h for h in fail_list if h["htype"] in ("idrac", "switch")]

    # Phase 2: Get bootstrap auth and fix
    fmt.line(f"  {fmt.C.BOLD}Phase 2: Repair{fmt.C.RESET}")
    fmt.blank()

    fixed = 0
    failed = 0

    # Headless mode support
    headless = getattr(args, "headless", False)
    bootstrap_key = getattr(args, "bootstrap_key", None) or ""
    bootstrap_user = getattr(args, "bootstrap_user", "root") or "root"

    # ── Linux-family ──
    if linux_broken:
        fmt.line(f"  {fmt.C.BOLD}Linux-family hosts ({len(linux_broken)}){fmt.C.RESET}")
        fmt.blank()

        if headless:
            auth_pass = ""
            auth_key = bootstrap_key
            auth_user = bootstrap_user
            if not auth_key:
                # Try reading password from --password-file
                pw_file = getattr(args, "password_file", None)
                if pw_file and os.path.isfile(pw_file):
                    with open(pw_file) as f:
                        auth_pass = f.read().strip()
                else:
                    fmt.step_fail("Headless mode requires --bootstrap-key or --password-file")
                    failed += len(linux_broken)
                    linux_broken = []
        else:
            fmt.line(f"  {fmt.C.DIM}Need bootstrap auth to reach these hosts and deploy {svc_name}.{fmt.C.RESET}")
            fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Password (same for all)")
            fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
            fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
            fmt.blank()

            choice = _input("Choice", "A").upper()
            if choice == "S":
                fmt.step_warn("Skipping Linux hosts")
                failed += len(linux_broken)
                linux_broken = []
                auth_pass = auth_key = auth_user = ""
            else:
                auth_user = _input("Bootstrap user (root or sudo account)", "root")
                auth_pass, auth_key = _get_auth_creds(choice, "broken Linux hosts")

        for h in linux_broken:
            fmt.blank()
            fmt.line(f"  {fmt.C.BOLD}{h['label']}{fmt.C.RESET} ({h['ip']}) [{h['htype']}]")
            if _deploy_to_host_dispatch(h["ip"], h["htype"], ctx, auth_pass, auth_key, auth_user):
                # Verify it worked
                ok, _ = _verify_host(h["ip"], h["htype"], svc_name, key_file, rsa_file)
                if ok:
                    fmt.step_ok(f"{h['label']}: {svc_name} deployed and verified")
                    fixed += 1
                else:
                    fmt.step_fail(f"{h['label']}: deployed but verification failed")
                    failed += 1
            else:
                failed += 1

    # ── pfSense ──
    if pfsense_broken:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}pfSense hosts ({len(pfsense_broken)}){fmt.C.RESET}")
        fmt.blank()

        if headless:
            auth_pass = ""
            auth_key = bootstrap_key
            auth_user = bootstrap_user
        else:
            fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Admin password")
            fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
            fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
            fmt.blank()

            choice = _input("Choice", "A").upper()
            if choice == "S":
                fmt.step_warn("Skipping pfSense hosts")
                failed += len(pfsense_broken)
                pfsense_broken = []
                auth_pass = auth_key = auth_user = ""
            else:
                auth_user = _input("Auth user", "admin")
                auth_pass, auth_key = _get_auth_creds(choice, "pfSense")

        for h in pfsense_broken:
            fmt.blank()
            fmt.line(f"  {fmt.C.BOLD}{h['label']}{fmt.C.RESET} ({h['ip']}) [pfsense]")
            if _deploy_to_host_dispatch(h["ip"], "pfsense", ctx, auth_pass, auth_key, auth_user):
                ok, _ = _verify_host(h["ip"], "pfsense", svc_name, key_file, rsa_file)
                if ok:
                    fmt.step_ok(f"{h['label']}: {svc_name} deployed and verified")
                    fixed += 1
                else:
                    fmt.step_fail(f"{h['label']}: deployed but verification failed")
                    failed += 1
            else:
                failed += 1

    # ── Devices (iDRAC, switch) ──
    if device_broken:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Device hosts ({len(device_broken)}){fmt.C.RESET}")
        fmt.blank()

        if not ctx["rsa_pubkey"]:
            fmt.step_fail("No RSA public key — iDRAC/switch require RSA")
            failed += len(device_broken)
        else:
            if headless:
                dev_pass = ""
                dev_user = bootstrap_user
                # Try device credentials
                dev_creds = getattr(args, "device_credentials", None)
                pw_file = getattr(args, "device_password_file", None) or getattr(args, "password_file", None)
                if pw_file and os.path.isfile(pw_file):
                    with open(pw_file) as f:
                        dev_pass = f.read().strip()
                dev_user = getattr(args, "device_user", "root") or "root"
            else:
                fmt.line(f"  {fmt.C.DIM}Need admin access to create {svc_name} on devices.{fmt.C.RESET}")
                fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Admin password")
                fmt.line(f"    {fmt.C.BOLD}S{fmt.C.RESET}) Skip")
                fmt.blank()

                choice = _input("Choice", "A").upper()
                if choice == "S":
                    fmt.step_warn("Skipping device hosts")
                    failed += len(device_broken)
                    device_broken = []
                    dev_pass = dev_user = ""
                else:
                    dev_user = _input("Auth user", "root")
                    rc, _, _ = _run(["which", "sshpass"])
                    if rc != 0:
                        fmt.step_fail("'sshpass' not installed — required for device auth")
                        failed += len(device_broken)
                        device_broken = []
                        dev_pass = ""
                    else:
                        dev_pass = getpass.getpass(f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for device admin ({dev_user}): ")

            for h in device_broken:
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h['label']}{fmt.C.RESET} ({h['ip']}) [{h['htype']}]")
                if _deploy_to_host_dispatch(h["ip"], h["htype"], ctx, dev_pass, "", dev_user):
                    ok, _ = _verify_host(h["ip"], h["htype"], svc_name, key_file, rsa_file)
                    if ok:
                        fmt.step_ok(f"{h['label']}: {svc_name} deployed and verified")
                        fixed += 1
                    else:
                        fmt.step_fail(f"{h['label']}: deployed but verification failed")
                        failed += 1
                else:
                    failed += 1

    # Summary
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Results:{fmt.C.RESET} "
             f"{fmt.C.GREEN}{fixed} fixed{fmt.C.RESET}, "
             f"{fmt.C.RED}{failed} failed{fmt.C.RESET}")

    if failed:
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Re-run 'freq init --fix' after resolving auth issues.{fmt.C.RESET}")
    elif unreachable_list:
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}{len(unreachable_list)} hosts unreachable — re-run when they come online.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0 if failed == 0 else 1


# ═══════════════════════════════════════════════════════════════════
# --reset mode
# ═══════════════════════════════════════════════════════════════════

def _init_reset(cfg):
    """Reset FREQ to pre-init state."""
    fmt.header("Init Reset")
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will wipe vault, roles, and initialization state.{fmt.C.RESET}")
    fmt.blank()

    if not _confirm("Are you sure?"):
        fmt.line(f"  {fmt.C.DIM}Cancelled.{fmt.C.RESET}")
        return 0

    marker = os.path.join(cfg.conf_dir, ".initialized")
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")

    for path, label in [
        (cfg.vault_file, "Vault"),
        (roles_file, "Roles"),
        (marker, "Init marker"),
    ]:
        if os.path.isfile(path):
            os.unlink(path)
            fmt.step_ok(f"{label} removed: {path}")
        else:
            fmt.step_warn(f"{label} not found: {path}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}Reset complete. Run 'freq init' to start fresh.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


# ═══════════════════════════════════════════════════════════════════
# --uninstall: fleet-wide teardown
# ═══════════════════════════════════════════════════════════════════

def _uninstall_interactive(cfg):
    """Interactive uninstall — remove FREQ service account from ALL hosts."""
    # Must be root
    if os.geteuid() != 0:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}freq init --uninstall must be run as root.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run: sudo freq init --uninstall{fmt.C.RESET}")
        fmt.blank()
        return 1

    svc_name = cfg.ssh_service_account
    ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_key = os.path.join(cfg.key_dir, "freq_id_rsa")

    fmt.header("Init — Uninstall")
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will remove the FREQ service account from ALL hosts.{fmt.C.RESET}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Service account: {fmt.C.BOLD}{svc_name}{fmt.C.RESET}")

    # Count targets
    targets = []
    if cfg.pve_nodes:
        for ip in cfg.pve_nodes:
            targets.append((ip, "pve", f"PVE {ip}"))
    if cfg.hosts:
        pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
        for h in cfg.hosts:
            if h.ip not in pve_set:
                targets.append((h.ip, h.htype, f"{h.label} ({h.ip})"))

    fmt.line(f"  {fmt.C.DIM}Remote hosts:    {len(targets)}{fmt.C.RESET}")
    fmt.blank()

    fmt.line(f"  {fmt.C.RED}This will:{fmt.C.RESET}")
    fmt.line(f"    - Delete account '{svc_name}' + home dir on {len(targets)} remote hosts")
    fmt.line(f"    - Remove sudoers, SSH keys, group membership on remote hosts")
    fmt.line(f"    - Delete local SSH keypairs ({cfg.key_dir}/)")
    fmt.line(f"    - Remove vault, roles, init marker")
    fmt.line(f"    - Remove local sudoers for '{svc_name}'")
    fmt.line(f"    - Delete local account '{svc_name}'")
    fmt.blank()

    if not _confirm("Proceed with uninstall?"):
        fmt.line(f"  {fmt.C.DIM}Cancelled.{fmt.C.RESET}")
        return 0

    # Double-confirm
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}This cannot be undone. Type 'UNINSTALL' to confirm:{fmt.C.RESET}")
    try:
        ans = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        fmt.line(f"  {fmt.C.DIM}Cancelled.{fmt.C.RESET}")
        return 0
    if ans != "UNINSTALL":
        fmt.line(f"  {fmt.C.DIM}Cancelled.{fmt.C.RESET}")
        return 0

    return _uninstall_execute(cfg, svc_name, ed_key, rsa_key, targets)


def _uninstall_headless(cfg):
    """Non-interactive uninstall — no prompts."""
    if os.geteuid() != 0:
        fmt.line(f"  {fmt.C.RED}freq init --uninstall --headless must be run as root.{fmt.C.RESET}")
        return 1

    svc_name = cfg.ssh_service_account
    ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_key = os.path.join(cfg.key_dir, "freq_id_rsa")

    targets = []
    if cfg.pve_nodes:
        for ip in cfg.pve_nodes:
            targets.append((ip, "pve", f"PVE {ip}"))
    if cfg.hosts:
        pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
        for h in cfg.hosts:
            if h.ip not in pve_set:
                targets.append((h.ip, h.htype, f"{h.label} ({h.ip})"))

    fmt.header("Init — Uninstall (headless)")
    fmt.blank()
    return _uninstall_execute(cfg, svc_name, ed_key, rsa_key, targets)


def _uninstall_execute(cfg, svc_name, ed_key, rsa_key, targets):
    """Execute the uninstall — shared by interactive and headless modes.

    Order: remote hosts first (need FREQ key), then local cleanup.
    Returns 0 on full success, 1 on partial failure.
    """
    ok = fail = skip = 0

    # ── Phase 1: Remote host teardown ──
    if targets:
        fmt.blank()
        fmt.divider("Phase 1/2: Remote Host Teardown")
        fmt.blank()

        has_ed_key = os.path.isfile(ed_key)
        has_rsa_key = os.path.isfile(rsa_key)

        if not has_ed_key and not has_rsa_key:
            fmt.step_warn("No FREQ SSH keys found — skipping remote hosts")
            fmt.line(f"  {fmt.C.DIM}Remote accounts must be removed manually.{fmt.C.RESET}")
            skip = len(targets)
        else:
            for ip, htype, label in targets:
                fmt.line(f"  {fmt.C.BOLD}{label}{fmt.C.RESET} [{htype}]")

                success, err_info = _remove_from_host_dispatch(
                    ip, htype, svc_name, ed_key, rsa_key,
                )

                if success:
                    if err_info == "not_found":
                        fmt.step_ok(f"Account not present (already clean)")
                    elif err_info == "key_only":
                        fmt.step_warn(f"SSH key removed (account needs manual removal — no sudo on pfSense)")
                    else:
                        fmt.step_ok(f"Removed from {label}")
                    ok += 1
                elif _is_skip_error(err_info):
                    fmt.step_warn(f"{_skip_reason(err_info)} — skipped")
                    skip += 1
                else:
                    fmt.step_fail(f"Failed: {err_info[:60]}")
                    fail += 1

        fmt.blank()
        fmt.line(f"  Remote: {fmt.C.GREEN}{ok} removed{fmt.C.RESET}, "
                 f"{fmt.C.RED}{fail} failed{fmt.C.RESET}, "
                 f"{fmt.C.YELLOW}{skip} skipped{fmt.C.RESET}")

    # ── Phase 2: Local cleanup ──
    fmt.blank()
    fmt.divider("Phase 2/2: Local Cleanup")
    fmt.blank()

    # Sudoers
    sudoers_file = f"/etc/sudoers.d/freq-{svc_name}"
    if os.path.isfile(sudoers_file):
        os.unlink(sudoers_file)
        fmt.step_ok(f"Sudoers removed: {sudoers_file}")
    else:
        fmt.step_warn(f"Sudoers not found: {sudoers_file}")

    # SSH keys
    for key_file, label in [
        (ed_key, "ed25519 private key"),
        (f"{ed_key}.pub", "ed25519 public key"),
        (rsa_key, "RSA private key"),
        (f"{rsa_key}.pub", "RSA public key"),
    ]:
        if os.path.isfile(key_file):
            os.unlink(key_file)
            fmt.step_ok(f"{label} removed")
        else:
            fmt.step_warn(f"{label} not found")

    # Remove key directory if empty
    if os.path.isdir(cfg.key_dir):
        try:
            os.rmdir(cfg.key_dir)
            fmt.step_ok(f"Key dir removed: {cfg.key_dir}")
        except OSError:
            fmt.step_warn(f"Key dir not empty: {cfg.key_dir}")

    # Vault
    if os.path.isfile(cfg.vault_file):
        os.unlink(cfg.vault_file)
        fmt.step_ok("Vault removed")
    else:
        fmt.step_warn("Vault not found")

    # Roles
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    if os.path.isfile(roles_file):
        os.unlink(roles_file)
        fmt.step_ok("Roles removed")
    else:
        fmt.step_warn("Roles not found")

    # Init marker
    marker = os.path.join(cfg.conf_dir, ".initialized")
    if os.path.isfile(marker):
        os.unlink(marker)
        fmt.step_ok("Init marker removed")
    else:
        fmt.step_warn("Init marker not found")

    # Local service account
    rc, _, _ = _run(["id", svc_name])
    if rc == 0:
        # Kill processes first
        _run(["pkill", "-u", svc_name])
        # Delete account + home
        rc2, _, err2 = _run(["userdel", "-r", svc_name])
        if rc2 == 0:
            fmt.step_ok(f"Local account '{svc_name}' deleted (+ home dir)")
        else:
            # Try without -r
            rc3, _, _ = _run(["userdel", svc_name])
            if rc3 == 0:
                fmt.step_ok(f"Local account '{svc_name}' deleted (home dir remains)")
            else:
                fmt.step_fail(f"Could not delete local account: {err2[:60]}")
    else:
        fmt.step_warn(f"Local account '{svc_name}' not found")

    # Local group cleanup (userdel usually removes the primary group,
    # but clean up if it's still lingering)
    rc, _, _ = _run(["getent", "group", svc_name])
    if rc == 0:
        rc2, _, _ = _run(["groupdel", svc_name])
        if rc2 == 0:
            fmt.step_ok(f"Group '{svc_name}' deleted")
        else:
            fmt.step_warn(f"Could not delete group '{svc_name}' (may have members)")
    else:
        fmt.step_ok(f"Group '{svc_name}' already removed")

    # Summary
    fmt.blank()
    fmt.divider("Uninstall Complete")
    fmt.blank()
    if fail == 0 and skip == 0:
        fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}FREQ fully uninstalled.{fmt.C.RESET}")
    elif fail == 0:
        fmt.line(f"  {fmt.C.YELLOW}FREQ uninstalled ({skip} host(s) skipped — unreachable).{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Clean up skipped hosts manually or re-run when reachable.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.RED}FREQ partially uninstalled ({fail} failure(s), {skip} skipped).{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Check failures above and clean up manually.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}To reinstall: sudo freq init{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()

    logger.info("uninstall complete", removed=ok, failed=fail, skipped=skip)
    return 0 if fail == 0 else 1


def _uninstall_dry_run(cfg):
    """Show what --uninstall would remove without making changes."""
    svc_name = cfg.ssh_service_account

    fmt.header("Init — Uninstall (dry run)")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}This shows what 'freq init --uninstall' would remove:{fmt.C.RESET}")
    fmt.blank()

    steps = []
    step_n = 1

    # Remote hosts
    if cfg.pve_nodes:
        for ip in cfg.pve_nodes:
            steps.append(f"{step_n}. Remove '{svc_name}' from PVE {ip}: userdel + sudoers + authorized_keys")
            step_n += 1

    if cfg.hosts:
        pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
        for h in cfg.hosts:
            if h.ip in pve_set:
                continue
            if h.htype in ("linux", "pve", "docker", "truenas"):
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): userdel + sudoers + key [{h.htype}]")
            elif h.htype == "pfsense":
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): SSH key only (pfSense — manual account removal)")
            elif h.htype == "idrac":
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): disable slot + clear RSA key [iDRAC]")
            elif h.htype == "switch":
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): no username + clear pubkey-chain [switch]")
            else:
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): [{h.htype}]")
            step_n += 1

    # Local cleanup
    steps.extend([
        f"{step_n}. Remove local sudoers: /etc/sudoers.d/freq-{svc_name}",
        f"{step_n + 1}. Delete SSH keys: {cfg.key_dir}/freq_id_ed25519, freq_id_rsa (+ .pub)",
        f"{step_n + 2}. Delete vault: {cfg.vault_file}",
        f"{step_n + 3}. Delete roles: {cfg.conf_dir}/roles.conf",
        f"{step_n + 4}. Delete init marker: {cfg.conf_dir}/.initialized",
        f"{step_n + 5}. Delete local account '{svc_name}' + home directory",
    ])

    for step in steps:
        fmt.line(f"    {step}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Run 'sudo freq init --uninstall' to execute.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


# ═══════════════════════════════════════════════════════════════════
# --dry-run mode
# ═══════════════════════════════════════════════════════════════════

def _init_dry_run(cfg):
    """Show what init would do."""
    fmt.header("Init — Dry Run")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}This shows what 'freq init' would do without making changes:{fmt.C.RESET}")
    fmt.blank()

    steps = [
        "1. Check prerequisites (ssh, ssh-keygen, openssl)",
        "2. Create data directories",
        "3. Configure cluster settings (PVE nodes, gateway, SSH mode)",
        f"4. Create service account '{cfg.ssh_service_account}' with NOPASSWD sudo",
        f"5. Generate ed25519 + RSA-4096 SSH keypairs in {cfg.key_dir}/",
        "6. Deploy public key to local service account",
        "7. Initialize encrypted vault (AES-256-CBC)",
        "8. Store service account password in vault",
    ]

    step_n = 9
    if cfg.pve_nodes:
        for ip in cfg.pve_nodes:
            steps.append(f"{step_n}. Deploy to PVE node {ip}: useradd + sudo + ed25519 key")
            step_n += 1
    if cfg.hosts:
        for h in cfg.hosts:
            if h.htype in ("linux", "pve", "docker", "truenas"):
                steps.append(f"{step_n}. Deploy to {h.label} ({h.ip}): useradd + sudo + ed25519 key")
            elif h.htype == "pfsense":
                steps.append(f"{step_n}. Deploy to {h.label} ({h.ip}): pw useradd + ed25519 key (FreeBSD, no sudo)")
            elif h.htype == "idrac":
                steps.append(f"{step_n}. Deploy to {h.label} ({h.ip}): racadm user + RSA key (iDRAC)")
            elif h.htype == "switch":
                steps.append(f"{step_n}. Deploy to {h.label} ({h.ip}): IOS username + RSA pubkey-chain (switch)")
            else:
                steps.append(f"{step_n}. Deploy to {h.label} ({h.ip}): [{h.htype}]")
            step_n += 1

    steps.extend([
        f"{step_n}. Configure RBAC roles (admin for current user + service account)",
        f"{step_n + 1}. Verify all steps completed (platform-aware)",
        f"{step_n + 2}. Write .initialized marker",
    ])

    for step in steps:
        fmt.line(f"    {step}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Run 'freq init' (as root) to execute.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _update_toml(cfg, section, key, value):
    """Update a value in freq.toml."""
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    if not os.path.isfile(toml_path):
        return

    with open(toml_path) as f:
        lines = f.readlines()
    in_section = False
    updated = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and stripped.startswith(f"{key} "):
            lines[i] = f'{key} = "{value}"\n'
            updated = True
            break

    if not updated:
        # Append to section or create it
        section_exists = any(l.strip() == f"[{section}]" for l in lines)
        if section_exists:
            # Find end of section
            in_sect = False
            for i, line in enumerate(lines):
                if line.strip() == f"[{section}]":
                    in_sect = True
                    continue
                if in_sect and (line.strip().startswith("[") or i == len(lines) - 1):
                    lines.insert(i, f'{key} = "{value}"\n')
                    updated = True
                    break
        else:
            lines.append(f"\n[{section}]\n{key} = \"{value}\"\n")

    with open(toml_path, "w") as f:
        f.writelines(lines)


def cmd_configure(cfg: FreqConfig, pack, args) -> int:
    """Reconfigure FREQ settings interactively."""
    fmt.header("Configure")
    fmt.blank()

    fmt.line(f"{fmt.C.BOLD}Current configuration:{fmt.C.RESET}")
    fmt.blank()

    settings = [
        ("Version", cfg.version),
        ("Brand", cfg.brand),
        ("Build", cfg.build),
        ("SSH Account", cfg.ssh_service_account),
        ("SSH Timeout", f"{cfg.ssh_connect_timeout}s"),
        ("Max Parallel", str(cfg.ssh_max_parallel)),
        ("PVE Nodes", ", ".join(cfg.pve_nodes) or "none"),
        ("Cluster", cfg.cluster_name),
        ("Timezone", cfg.timezone),
        ("Install Dir", cfg.install_dir),
    ]

    for label, value in settings:
        fmt.line(f"  {fmt.C.GRAY}{label:>16}:{fmt.C.RESET}  {value}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Edit {os.path.join(cfg.conf_dir, 'freq.toml')} to change settings.{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GRAY}Then run 'freq doctor' to verify.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


# ═══════════════════════════════════════════════════════════════════
# HEADLESS MODE — agent-driven, zero prompts
# ═══════════════════════════════════════════════════════════════════

def _init_headless(cfg, args):
    """Non-interactive init for agent-driven deployment.

    Bootstraps service account on all fleet hosts using an existing privileged
    account (e.g., root or a sudo-capable user). No interactive prompts.

    Usage:
      sudo freq init --headless --bootstrap-key /path/to/key --password-file /path/to/pass
    """
    global INIT_MARKER
    INIT_MARKER = os.path.join(cfg.conf_dir, ".initialized")

    if os.geteuid() != 0:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}freq init --headless must be run as root.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run: sudo freq init --headless ...{fmt.C.RESET}")
        fmt.blank()
        return 1

    bootstrap_key = getattr(args, "bootstrap_key", None)
    bootstrap_user = getattr(args, "bootstrap_user", "root")
    bootstrap_pass_file = getattr(args, "bootstrap_password_file", None)
    password_file = getattr(args, "password_file", None)
    device_credentials_file = getattr(args, "device_credentials", None)
    # Legacy flags (deprecated, still functional as fallback)
    device_password_file = getattr(args, "device_password_file", None)
    device_user = getattr(args, "device_user", "root")

    # Read bootstrap password from file if provided
    bootstrap_pass = ""
    if bootstrap_pass_file and os.path.isfile(bootstrap_pass_file):
        with open(bootstrap_pass_file) as f:
            bootstrap_pass = f.read().strip()

    # Auto-detect bootstrap key if not specified
    if not bootstrap_key:
        for candidate in [
            f"/home/{bootstrap_user}/.ssh/id_ed25519",
            f"/home/{bootstrap_user}/.ssh/id_rsa",
        ]:
            if os.path.isfile(candidate):
                bootstrap_key = candidate
                break

    if (not bootstrap_key or not os.path.isfile(bootstrap_key)) and not bootstrap_pass:
        fmt.line(f"  {fmt.C.RED}No bootstrap auth found.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Use --bootstrap-key PATH or --bootstrap-password-file PATH{fmt.C.RESET}")
        return 1

    # Read password from file
    if not password_file or not os.path.isfile(password_file):
        fmt.line(f"  {fmt.C.RED}--password-file required for headless mode.{fmt.C.RESET}")
        return 1

    with open(password_file) as f:
        svc_pass = f.read().strip()
    if len(svc_pass) < 4:
        fmt.line(f"  {fmt.C.RED}Password too short (min 4 chars){fmt.C.RESET}")
        return 1

    ctx = {
        "svc_name": cfg.ssh_service_account,
        "svc_pass": svc_pass,
        "key_path": "",
        "pubkey": "",
        "rsa_key_path": "",
        "rsa_pubkey": "",
    }

    fmt.header("Init — Headless Mode")
    fmt.blank()
    if bootstrap_key:
        fmt.line(f"  Bootstrap: {fmt.C.CYAN}{bootstrap_user}{fmt.C.RESET} via key {fmt.C.CYAN}{bootstrap_key}{fmt.C.RESET}")
    else:
        fmt.line(f"  Bootstrap: {fmt.C.CYAN}{bootstrap_user}{fmt.C.RESET} via password (sshpass)")
    fmt.line(f"  Service account: {fmt.C.CYAN}{ctx['svc_name']}{fmt.C.RESET}")
    fmt.blank()

    # ── Phase 1: Prerequisites ──
    _phase(1, 8, "Prerequisites")
    if not _phase_welcome(cfg):
        return 1

    # ── Phase 2: Cluster Configuration ──
    _phase(2, 8, "Cluster Configuration")
    _phase_configure(cfg, args)

    # ── Phase 3: Local Service Account ──
    _phase(3, 8, "Local Service Account")
    if not _headless_local_account(cfg, ctx):
        return 1

    # ── Phase 4: SSH Keys ──
    _phase(4, 8, "SSH Key Generation")
    _phase_ssh_keys(cfg, ctx)

    # ── Phase 5: Fleet Deployment ──
    _phase(5, 8, "Fleet Deployment")

    # Import hosts from --hosts-file if provided (before fleet deploy so all targets are included)
    hosts_file_arg = getattr(args, "hosts_file", None)
    if hosts_file_arg and os.path.isfile(hosts_file_arg):
        fmt.step_start(f"Importing fleet hosts from {hosts_file_arg}")
        shutil.copy2(hosts_file_arg, cfg.hosts_file)
        from freq.core.config import load_hosts
        try:
            cfg.hosts = load_hosts(cfg.hosts_file)
            fmt.step_ok(f"Imported {len(cfg.hosts)} host(s) from {hosts_file_arg}")
        except Exception as e:
            fmt.step_fail(f"Failed to reload hosts: {e}")

    # Load per-device credentials (new style) or fall back to legacy single-file
    device_creds = _load_device_credentials(device_credentials_file)
    if device_creds:
        fmt.step_ok(f"Per-device credentials loaded: {', '.join(sorted(device_creds.keys()))}")
    elif device_password_file:
        fmt.step_warn("Using deprecated --device-password-file (migrate to --device-credentials)")

    _headless_fleet_deploy(cfg, ctx, bootstrap_key, bootstrap_user,
                           bootstrap_pass=bootstrap_pass,
                           device_password_file=device_password_file,
                           device_user=device_user,
                           device_creds=device_creds)

    # ── Phase 6: PDM Setup ──
    _phase(6, 8, "PDM Setup")
    _phase_pdm(cfg, ctx, args)

    # ── Phase 7: RBAC ──
    _phase(7, 8, "RBAC Setup")
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    existing = ""
    if os.path.isfile(roles_file):
        with open(roles_file) as f:
            existing = f.read()
    with open(roles_file, "a") as f:
        if f"{bootstrap_user}:" not in existing:
            f.write(f"{bootstrap_user}:admin\n")
            fmt.step_ok(f"Added {bootstrap_user} as admin")
        else:
            fmt.step_ok(f"{bootstrap_user} already in roles")
        svc_name = ctx["svc_name"]
        if f"{svc_name}:" not in existing:
            f.write(f"{svc_name}:admin\n")
            fmt.step_ok(f"Added {svc_name} as admin")
        else:
            fmt.step_ok(f"{svc_name} already in roles")

    # ── Phase 8: Verification ──
    _phase(8, 8, "Verification")
    verified = _phase_verify(cfg, ctx)

    # Write marker
    with open(INIT_MARKER, "w") as f:
        f.write(f"{cfg.version}\n")

    fmt.blank()
    if verified:
        fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}FREQ initialized successfully — headless.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.YELLOW}Init completed with warnings. Run 'freq init --check' to review.{fmt.C.RESET}")
    fmt.blank()

    logger.info("headless init complete", service_account=ctx["svc_name"])
    return 0 if verified else 1


def _headless_local_account(cfg, ctx):
    """Create service account locally — no prompts."""
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]

    # Account (useradd creates matching group automatically)
    rc, _, _ = _run(["id", svc_name])
    if rc != 0:
        _run(["useradd", "-m", "-s", "/bin/bash", svc_name])
        rc2, _, _ = _run(["id", svc_name])
        if rc2 == 0:
            fmt.step_ok(f"Account '{svc_name}' created")
        else:
            fmt.step_fail(f"Failed to create '{svc_name}'")
            return False
    else:
        fmt.step_ok(f"Account '{svc_name}' exists")

    # Password
    p = subprocess.Popen(["/usr/sbin/chpasswd"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.communicate(input=f"{svc_name}:{svc_pass}\n".encode())
    if p.returncode == 0:
        fmt.step_ok("Password set")
    else:
        fmt.step_warn("chpasswd failed — password may not be set")

    # Sudoers
    _setup_sudoers(svc_name)

    # Vault
    if not os.path.exists(cfg.vault_file):
        from freq.modules.vault import vault_init
        vault_init(cfg)
    from freq.modules.vault import vault_set
    vault_key = f"{svc_name}-pass"
    vault_set(cfg, "DEFAULT", vault_key, svc_pass)
    fmt.step_ok(f"Password stored in vault (key: {vault_key})")

    # Config
    _update_toml(cfg, "ssh", "service_account", svc_name)
    fmt.step_ok(f"Config: service_account = {svc_name}")

    return True


def _headless_fleet_deploy(cfg, ctx, bootstrap_key, bootstrap_user,
                           bootstrap_pass="",
                           device_password_file=None, device_user="root",
                           device_creds=None):
    """Deploy service account to PVE + fleet hosts using bootstrap credentials.

    Uses the unified platform dispatcher for all host types.
    Supports bootstrap via SSH key (--bootstrap-key) or password (--bootstrap-password-file).

    device_creds: dict from _load_device_credentials() — per-device-type auth:
        {"pfsense": {"user": "root", "password": "..."}, "switch": {"user": "gigecolo", "password": "..."}}
    Falls back to legacy device_password_file + device_user if device_creds not provided.
    """
    if device_creds is None:
        device_creds = {}
    # Collect all targets: PVE nodes + fleet hosts (deduplicated by IP)
    seen_ips = set()
    targets = []

    for i, ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else ip
        targets.append({"ip": ip, "label": name, "htype": "pve"})
        seen_ips.add(ip)

    for h in cfg.hosts:
        if h.ip not in seen_ips:
            targets.append({"ip": h.ip, "label": h.label, "htype": h.htype})
            seen_ips.add(h.ip)

    if not targets:
        fmt.line(f"  {fmt.C.DIM}No targets found in config.{fmt.C.RESET}")
        return

    fmt.line(f"  {fmt.C.DIM}Deploying to {len(targets)} host(s) via {bootstrap_user}...{fmt.C.RESET}")
    fmt.blank()

    # Read device password if provided
    device_pass = ""
    if device_password_file and os.path.isfile(device_password_file):
        with open(device_password_file) as f:
            device_pass = f.read().strip()
        fmt.step_ok(f"Device password loaded from {device_password_file}")

    ok = fail = skip = 0
    for t in targets:
        ip = t["ip"]
        label = t["label"]
        htype = t["htype"]

        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}{label}{fmt.C.RESET} ({ip}) [{htype}]")

        # Determine auth credentials based on host type
        if htype in DEVICE_HTYPES and htype in device_creds:
            # Per-device credentials from --device-credentials TOML
            dcred = device_creds[htype]
            auth_user = dcred["user"]
            auth_pass = dcred["password"]
            auth_key = ""
        elif htype in ("idrac", "switch"):
            # Legacy fallback: device_password_file + device_user
            auth_pass = device_pass or ctx["svc_pass"]
            auth_key = ""
            auth_user = device_user
            if not device_pass:
                fmt.step_warn("No device credentials — using service account password for device auth")
        elif htype == "pfsense":
            # pfSense: root IS the admin. No sudo — must auth as root.
            # bootstrap_user (service account) can connect but can't create users.
            auth_user = "root"
            if device_pass:
                auth_pass = device_pass
                auth_key = ""
            else:
                auth_pass = ""
                auth_key = bootstrap_key
        elif htype == "truenas":
            # TrueNAS: use bootstrap creds by default, device_creds override if present
            if bootstrap_key:
                auth_pass = ""
                auth_key = bootstrap_key
            else:
                auth_pass = bootstrap_pass
                auth_key = ""
            auth_user = bootstrap_user
        else:
            # Linux-family: use bootstrap credentials (key or password)
            if bootstrap_key:
                auth_pass = ""
                auth_key = bootstrap_key
            else:
                auth_pass = bootstrap_pass
                auth_key = ""
            auth_user = bootstrap_user

        # Check connectivity for Linux-family hosts (bootstrap creds)
        # Skip for devices (iDRAC/switch) and pfSense — deployers have own checks
        if htype not in ("idrac", "switch", "pfsense"):
            if bootstrap_key:
                ssh_check = [
                    "ssh", "-n", "-i", bootstrap_key,
                    "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=accept-new",
                    f"{bootstrap_user}@{ip}", "echo OK",
                ]
            else:
                # Password-based connectivity check via sshpass (tempfile, not CLI arg)
                import tempfile
                _bp_fd, _bp_path = tempfile.mkstemp(prefix="freq-bp-")
                os.write(_bp_fd, bootstrap_pass.encode())
                os.close(_bp_fd)
                ssh_check = [
                    "sshpass", "-f", _bp_path,
                    "ssh", "-n",
                    "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "PubkeyAuthentication=no",
                    f"{bootstrap_user}@{ip}", "echo OK",
                ]
            rc, _, err = _run(ssh_check, timeout=QUICK_CHECK_TIMEOUT)
            # Clean up temp password file if created
            if not bootstrap_key:
                try:
                    os.unlink(_bp_path)
                except OSError:
                    pass
            if rc != 0:
                if _is_skip_error(err):
                    fmt.step_warn(f"{label} ({ip}) — {_skip_reason(err)} (skipped)")
                    skip += 1
                else:
                    fmt.step_fail(f"Cannot connect ({err.strip()[:60]})")
                    fail += 1
                continue

        if _deploy_to_host_dispatch(ip, htype, ctx, auth_pass, auth_key, auth_user):
            ok += 1
        else:
            fail += 1

    # Persist device password for ongoing iDRAC/switch SSH access
    has_devices = any(t["htype"] in ("idrac", "switch") for t in targets)
    svc_pass = ctx.get("svc_pass", "")
    if has_devices and ok > 0 and svc_pass:
        svc_name = ctx.get("svc_name", "freq-admin")
        svc_home = os.path.expanduser("~" + svc_name)
        pass_path = os.path.join(svc_home, ".ssh", "switch-pass")
        try:
            os.makedirs(os.path.dirname(pass_path), mode=0o700, exist_ok=True)
            with open(pass_path, "w") as f:
                f.write(svc_pass)
            os.chmod(pass_path, 0o600)
            import pwd
            try:
                pw = pwd.getpwnam(svc_name)
                os.chown(pass_path, pw.pw_uid, pw.pw_gid)
            except (KeyError, PermissionError):
                pass
            fmt.step_ok(f"Device password saved to {pass_path}")
        except OSError as e:
            fmt.step_warn(f"Could not save device password: {e}")

    fmt.blank()
    fmt.line(f"  Fleet: {fmt.C.GREEN}{ok} OK{fmt.C.RESET}, "
             f"{fmt.C.RED}{fail} failed{fmt.C.RESET}, "
             f"{fmt.C.YELLOW}{skip} skipped{fmt.C.RESET}")
