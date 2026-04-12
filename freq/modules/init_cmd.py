"""FREQ init — first-run setup wizard and fleet deployment engine.

Domain: freq init [--headless] [--check] [--fix] [--uninstall]
        freq configure

10-phase deployment pipeline that takes a bare machine to a fully managed
fleet in one command: prerequisites → config → service account → SSH keys →
PVE node deployment → PDM setup → fleet host deployment → device deployment →
admin account → verification. Supports headless mode for automation.

Replaces: Ansible playbooks for initial setup ($0 but 100+ lines of YAML),
          manual SSH key distribution, hand-edited config files

Architecture:
    - Sequential phase execution with rollback awareness
    - SSH via subprocess (sshpass for initial auth, key auth after)
    - Config generation writes freq.toml, hosts.toml, vlans.toml
    - Device deployment dispatches to freq/deployers/ per device type
    - Headless mode reads all params from CLI flags, no prompts

Design decisions:
    - Must run as root. Creates service account with NOPASSWD sudo.
    - Interactive by default, --headless for CI/automation.
    - --check validates existing install, --fix repairs broken hosts.
    - --uninstall removes FREQ service account from all hosts.
"""

import base64
import datetime
import getpass
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from freq.core import audit, fmt
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
DEVICE_DEPLOY_TIMEOUT = 120  # Total timeout for iDRAC/switch deploy (all steps combined)

# iDRAC user slot range (slots 1-2 are reserved by Dell for root/admin)
IDRAC_SLOT_MIN = 3
IDRAC_SLOT_MAX = 17  # exclusive — range(3, 17) gives slots 3-16

# IOS SSH key line width (PEM line wrapping limit)
IOS_KEY_LINE_WIDTH = 72

# Agent deployment — single source of truth for remote path
AGENT_REMOTE_PATH = "/opt/freq-agent/collector.py"
AGENT_REMOTE_DIR = "/opt/freq-agent"

# Error markers in remote deployment scripts
MARKER_DEPLOY_OK = "DEPLOY_OK"
MARKER_SETUP_OK = "SETUP_OK"
MARKER_USERADD_FAIL = "USERADD_FAIL"
MARKER_CHPASSWD_FAIL = "CHPASSWD_FAIL"
MARKER_CLEAN_OK = "CLEAN_OK"

# Input validation patterns
_VALID_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_VALID_LABEL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _validate_username(name):
    """Validate a Linux username. Returns True if valid."""
    return bool(_VALID_USERNAME.match(name))


def _validate_label(label):
    """Validate a host label. Returns True if valid."""
    return bool(_VALID_LABEL.match(label))


def _gen_idrac_slot_check():
    """Generate human-readable single-command racadm slot queries.

    iDRAC SSH lands in a RACADM command interpreter, not a POSIX shell.
    Keep this shell-free so callers do not accidentally rely on command
    substitution, pipes, or semicolons that the BMC cannot execute.
    """
    return "\n".join(
        f"racadm get iDRAC.Users.{i}.UserName"
        for i in range(IDRAC_SLOT_MIN, IDRAC_SLOT_MAX)
    )


def _parse_idrac_username_output(output):
    """Extract a username value from `racadm get ...UserName` output."""
    for raw in (output or "").splitlines():
        line = raw.strip().replace("\r", "")
        if line.lower().startswith("username"):
            return line.split("=", 1)[1].strip()
    return ""


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
            if line.startswith(marker):
                val = line.split(marker, 1)[1].strip()
                if val.upper() in ("NULL", "(NULL)", "NONE"):
                    val = ""
                if val == svc_name:
                    existing_slot = i
                    break
                elif not val and target_slot is None:
                    target_slot = i
    return target_slot, existing_slot


def _query_idrac_slots(_ssh, extra_opts, svc_name):
    """Query iDRAC user slots one command at a time via RACADM."""
    target_slot = None
    existing_slot = None

    for slot in range(IDRAC_SLOT_MIN, IDRAC_SLOT_MAX):
        rc, out, err = _ssh(
            f"racadm get iDRAC.Users.{slot}.UserName",
            extra_opts=extra_opts,
            timeout=QUICK_CHECK_TIMEOUT,
        )
        if rc != 0:
            logger.warning(
                "idrac slot query failed",
                host=getattr(_ssh, "__name__", "idrac"),
                slot=slot,
                error=(err or out)[:120],
            )
            continue
        val = _parse_idrac_username_output(out)
        if val.upper() in ("NULL", "(NULL)", "NONE"):
            val = ""
        if val == svc_name:
            existing_slot = slot
            break
        if not val and target_slot is None:
            target_slot = slot

    return target_slot, existing_slot


def _run_idrac_command(_ssh, extra_opts, cmd, timeout=IDRAC_SETUP_TIMEOUT):
    """Run a single RACADM command and reject device-reported failures."""
    rc, out, err = _ssh(cmd, extra_opts=extra_opts, timeout=timeout)
    combined = f"{out}\n{err}".strip()
    if rc != 0:
        return False, combined
    bad_markers = (
        "command processing failed",
        "command not recognized",
        "error:",
        "rac9",
    )
    if any(marker in combined.lower() for marker in bad_markers):
        return False, combined
    return True, combined


def _persist_legacy_password_file(cfg, svc_name, password):
    """Persist one shared iDRAC/switch password for verification fallback."""
    if not password:
        return

    svc_home = os.path.expanduser("~" + svc_name)
    pass_path = os.path.join(svc_home, ".ssh", "switch-pass")
    try:
        os.makedirs(os.path.dirname(pass_path), mode=0o700, exist_ok=True)
        with open(pass_path, "w") as f:
            f.write(password)
        os.chmod(pass_path, 0o600)

        import pwd

        try:
            pw = pwd.getpwnam(svc_name)
            os.chown(pass_path, pw.pw_uid, pw.pw_gid)
            os.chown(os.path.dirname(pass_path), pw.pw_uid, pw.pw_gid)
        except (KeyError, PermissionError):
            pass

        cfg.legacy_password_file = pass_path

        toml_path = os.path.join(cfg.conf_dir, "freq.toml")
        try:
            with open(toml_path) as f:
                content = f.read()
            content = _update_toml_value(content, "legacy_password_file", pass_path)
            with open(toml_path, "w") as f:
                f.write(content)
        except OSError as e:
            fmt.step_warn(f"Could not update legacy_password_file in freq.toml: {e}")

        fmt.step_ok(f"Device password saved to {pass_path}")
        audit.record("password_save", pass_path, "success")
    except OSError as e:
        fmt.step_warn(f"Could not save device password to {pass_path}: {e}")


def _run(cmd, timeout=DEFAULT_CMD_TIMEOUT):
    """Run a command, return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, "", str(e)


# sshpass exit codes → human-readable explanations
_SSHPASS_ERRORS = {
    1: "invalid command line argument",
    2: "conflicting arguments",
    3: "runtime error",
    4: "unrecognized response from ssh",
    5: "wrong password",
    6: "host key unknown (sshpass cannot verify)",
}


def _ssh_error_msg(rc, err):
    """Return a human-readable SSH error string.

    When sshpass fails (e.g. wrong password), stderr is often empty.
    This translates sshpass exit codes into actionable messages so
    users don't see 'Cannot connect ()'.
    """
    msg = (err or "").strip()[:60]
    if msg:
        return msg
    # stderr is empty — check for sshpass exit codes
    sshpass_msg = _SSHPASS_ERRORS.get(rc)
    if sshpass_msg:
        return sshpass_msg
    if rc != 0:
        return f"SSH failed (exit {rc})"
    return "unknown error"


def _chown(owner, *paths, recursive=False):
    """chown with return-code check. Returns True on success, False on failure."""
    cmd = ["chown"]
    if recursive:
        cmd.append("-R")
    cmd.append(owner)
    cmd.extend(paths)
    rc, _, err = _run(cmd)
    if rc != 0:
        logger.error(f"chown failed: {' '.join(cmd)}: {err.strip()}")
        fmt.step_fail(f"Ownership change failed: {' '.join(str(p) for p in paths)}")
    return rc == 0


def _run_with_input(cmd, input_text, timeout=DEFAULT_CMD_TIMEOUT):
    """Run a command with stdin input, return (rc, stdout, stderr).

    Used for IOS switch config — commands must be piped via stdin,
    not passed as SSH exec arguments.
    """
    try:
        r = subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout)
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

    # Parse TOML — try tomllib first, fall back to manual parser
    # (tomllib rejects section names with colons like [switch:cisco]
    # which are valid in our format but not bare TOML keys)
    data = None
    if tomllib is not None:
        try:
            with open(cred_file, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            pass  # Fall through to manual parser
    if data is None:
        try:
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
        """Extract user + password from a credential entry.

        Supports two password sources (priority order):
            1. password_file = "/path/to/file"  — read password from file
            2. password = "inline"              — inline password value

        At least one must be present. password_file takes priority when both exist.
        Accepts both 'user' and 'username' as key for the account name.
        """
        user = entry.get("user") or entry.get("username") or "root"
        pw_file = entry.get("password_file", "")
        inline_pw = entry.get("password", "")
        if pw_file:
            try:
                with open(pw_file) as f:
                    password = f.read().strip()
            except (OSError, IOError) as e:
                if inline_pw:
                    # password_file unreadable but inline password available — use it
                    fmt.step_warn(f"Cannot read {label} password from {pw_file}, using inline password")
                    return {"user": user, "password": inline_pw}
                fmt.step_warn(f"Cannot read {label} password from {pw_file}: {e}")
                return None
            return {"user": user, "password": password}
        if inline_pw:
            return {"user": user, "password": inline_pw}
        fmt.step_warn(f"Device '{label}' has no password or password_file — skipped")
        return None

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
        if len(p1) < 8:
            fmt.step_fail("Password too short (min 8 characters)")
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
        json_output = getattr(args, "json_output", False)
        return _init_check(cfg, json_output=json_output)

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
        # Bootstrap auth (collected in Phase 2, reused by Phase 5)
        "bootstrap_key": "",
        "bootstrap_pass": "",
        "bootstrap_user": "root",
        "dry_run": dry_run,
    }

    total = 13
    init_start = time.monotonic()
    logger.info("init_start: interactive mode", phases=total)

    # Phase 1: Prerequisites
    _phase(1, total, "Prerequisites")
    _t = time.monotonic()
    if not _phase_welcome(cfg):
        return 1
    logger.perf("init_phase", time.monotonic() - _t, phase=1, name="prerequisites")

    # Phase 2: Cluster Configuration + VLAN Discovery
    _phase(2, total, "Cluster Configuration + VLAN Discovery")
    _t = time.monotonic()
    _phase_configure(cfg, args)
    # Collect bootstrap auth for PVE access
    _collect_bootstrap_auth(cfg, ctx, args)
    # Discover VLANs from PVE network config (using bootstrap creds)
    _discover_vlans_from_pve(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=2, name="configure")

    # Phase 3: Service Account
    _phase(3, total, "Service Account Setup")
    _t = time.monotonic()
    if _phase_service_account(cfg, ctx, args) != 0:
        return 1
    logger.perf("init_phase", time.monotonic() - _t, phase=3, name="service_account")

    # Phase 4: SSH Keys
    _phase(4, total, "SSH Key Generation")
    _t = time.monotonic()
    _phase_ssh_keys(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=4, name="ssh_keys")

    # Phase 5: PVE Node Deployment
    _phase(5, total, "PVE Node Deployment")
    _t = time.monotonic()
    _phase_pve_deploy(cfg, ctx, args)
    # Retry VLAN discovery if skipped in Phase 2 (now service account key is available)
    if not (getattr(cfg, "vlans", None)):
        _discover_vlans_from_pve(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=5, name="pve_deploy")

    # Phase 6: PVE API Token
    _phase(6, total, "PVE API Token")
    _t = time.monotonic()
    _phase_pve_api_token(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=6, name="pve_api_token")

    # Phase 7: Fleet Discovery
    _phase(7, total, "Fleet Discovery")
    _t = time.monotonic()
    _phase_fleet_discover(cfg, ctx, args)
    logger.perf("init_phase", time.monotonic() - _t, phase=7, name="fleet_discover")

    # Phase 8: Fleet Deployment
    _phase(8, total, "Fleet Deployment")
    _t = time.monotonic()
    _phase_fleet_deploy(cfg, ctx, args)
    logger.perf("init_phase", time.monotonic() - _t, phase=8, name="fleet_deploy")

    # Phase 9: Fleet Configuration
    _phase(9, total, "Fleet Configuration")
    _t = time.monotonic()
    _phase_fleet_configure(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=9, name="fleet_configure")

    # Phase 10: PDM Setup (optional)
    _phase(10, total, "PDM Setup")
    _t = time.monotonic()
    _phase_pdm(cfg, ctx, args)
    logger.perf("init_phase", time.monotonic() - _t, phase=10, name="pdm")

    # Phase 11: Admin Accounts
    _phase(11, total, "Admin Account Setup")
    _t = time.monotonic()
    _phase_admin_setup(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=11, name="admin_setup")

    # Phase 12: Verification
    _phase(12, total, "Verification")
    _t = time.monotonic()
    verified = _phase_verify(cfg, ctx)
    logger.perf("init_phase", time.monotonic() - _t, phase=12, name="verify")

    # Phase 13: Summary
    _phase(13, total, "Summary")
    _t = time.monotonic()
    _phase_summary(cfg, ctx, verified, pack)
    logger.perf("init_phase", time.monotonic() - _t, phase=13, name="summary")

    # Fix post-init ownership: service account owns data dirs, operator can read
    svc_name = ctx["svc_name"]
    for d in [cfg.data_dir, cfg.key_dir, cfg.vault_file, cfg.log_dir, cfg.conf_dir]:
        d_path = d if os.path.isdir(d) else os.path.dirname(d)
        if d_path and os.path.exists(d_path):
            try:
                subprocess.run(["chown", "-R", f"{svc_name}:{svc_name}", d_path],
                               capture_output=True, timeout=5)
            except Exception:
                pass
    # Make log/ and cache/ world-readable so operator commands don't warn.
    # Keep keys/ and vault/ at 700 (service-account only — security-sensitive).
    for d in [cfg.log_dir, os.path.join(cfg.data_dir, "cache")]:
        d_path = d if os.path.isdir(d) else os.path.dirname(d)
        if d_path and os.path.exists(d_path):
            try:
                subprocess.run(["chmod", "755", d_path], capture_output=True, timeout=5)
            except Exception:
                pass
    # conf/ should be readable by operators (not just service account)
    # Files inside conf/ must not be world-writable (init runs as root with umask 000)
    if cfg.conf_dir and os.path.exists(cfg.conf_dir):
        try:
            subprocess.run(["chmod", "755", cfg.conf_dir], capture_output=True, timeout=5)
            # Config files: owner rw, group/other read-only
            for f in os.listdir(cfg.conf_dir):
                fpath = os.path.join(cfg.conf_dir, f)
                if os.path.isfile(fpath):
                    os.chmod(fpath, 0o644)
                elif os.path.isdir(fpath):
                    os.chmod(fpath, 0o755)
        except Exception:
            pass

    logger.perf("init_total", time.monotonic() - init_start, phases=total)

    logger.info("init complete", service_account=ctx["svc_name"])
    return 0 if verified else 1


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: Welcome + Prerequisites
# ═══════════════════════════════════════════════════════════════════


def _phase_welcome(cfg):
    """Check prerequisites are installed."""
    logger.info("init_phase_start: Phase 1 - prerequisites", phase=1)
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
        logger.error("init_phase_failed: Phase 1 - prerequisites", phase=1, reason="missing_deps")
        return False

    # Create data directories
    fmt.blank()
    fmt.step_start("Creating data directories")
    dirs = [cfg.data_dir, cfg.vault_dir, cfg.key_dir, os.path.dirname(cfg.log_file)]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    fmt.step_ok(f"Data directories ready ({len(dirs)} created)")

    # Seed config files from .example templates
    _seed_config_files(cfg)

    logger.info("init_phase_complete: Phase 1 - prerequisites", phase=1)
    return True


def _seed_config_files(cfg):
    """Copy .example config files to create initial live configs if missing.

    Only copies when the live file does not exist — never overwrites.
    This gives fresh installs a working starting point.
    """
    examples = [
        "freq.toml",
        "hosts.toml",
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
        items = ", ".join(f'"{v}"' for v in value)
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
        r"^([ \t]*#?[ \t]*)(" + re.escape(key) + r")([ \t]*=[ \t]*)(.*)$",
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
                if ch == '"' and (i == 0 or stripped[i - 1] != "\\"):
                    in_str = not in_str
                elif ch == "#" and not in_str:
                    inline_comment = "  " + stripped[i:]
                    break

        # Replace: uncomment if commented, set new value
        new_line = f"{key} = {toml_val}{inline_comment}"
        content = content[: match.start()] + new_line + content[match.end() :]
        return content

    section_map = {
        "mode": "ssh",
        "nodes": "pve",
        "node_names": "pve",
        "api_token_id": "pve",
        "api_token_secret_path": "pve",
        "gateway": "vm.defaults",
        "nameserver": "vm.defaults",
        "protected_vmids": "safety",
        "protected_ranges": "safety",
        "cluster_name": "infrastructure",
        "timezone": "infrastructure",
        "pfsense_ip": "infrastructure",
        "truenas_ip": "infrastructure",
        "switch_ip": "infrastructure",
        "docker_dev_ip": "infrastructure",
        "tls_cert": "services",
        "tls_key": "services",
    }
    section_name = section_map.get(key)
    new_line = f"{key} = {toml_val}\n"

    if not section_name:
        if content and not content.endswith("\n"):
            content += "\n"
        return content + new_line

    section_header = f"[{section_name}]"
    section_pattern = re.compile(rf"(?m)^({re.escape(section_header)})\s*$")
    section_match = section_pattern.search(content)
    if not section_match:
        if content and not content.endswith("\n"):
            content += "\n"
        if content and not content.endswith("\n\n"):
            content += "\n"
        return content + f"{section_header}\n{new_line}"

    insert_at = len(content)
    next_section = re.search(r"(?m)^\[", content[section_match.end() :])
    if next_section:
        insert_at = section_match.end() + next_section.start()

    insertion = new_line
    if insert_at > 0 and content[insert_at - 1] != "\n":
        insertion = "\n" + insertion
    return content[:insert_at] + insertion + content[insert_at:]


def _phase_configure(cfg, args=None):
    """Interactive cluster configuration — writes freq.toml with user's details.

    Asks for PVE nodes, network settings, and cluster name. Skips values
    that are already configured (non-empty, non-default) unless user opts to
    reconfigure. In headless mode, uses CLI flags and defaults — no prompts.
    """
    logger.info("init_phase_start: Phase 2 - configure", phase=2)
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    if not os.path.isfile(toml_path):
        fmt.step_fail(f"freq.toml not found at {toml_path}")
        return

    with open(toml_path) as f:
        content = f.read()

    changed = False
    yes_flag = getattr(args, "yes", False) if args else False
    headless = getattr(args, "headless", False) if args else False

    # Extract CLI overrides
    cli_pve_nodes = getattr(args, "pve_nodes", None) if args else None
    cli_pve_names = getattr(args, "pve_node_names", None) if args else None
    cli_gateway = getattr(args, "gateway", None) if args else None
    cli_nameserver = getattr(args, "nameserver", None) if args else None
    cli_hosts_file = getattr(args, "hosts_file", None) if args else None
    cli_cluster_name = getattr(args, "cluster_name", None) if args else None
    cli_ssh_mode = getattr(args, "ssh_mode", None) if args else None

    from freq.core import validate as _val

    def _invalid_ip_values(values):
        return [value for value in values if value and not _val.ip(value)]

    # ── PVE Nodes ──
    if cli_pve_nodes:
        # CLI override — skip interactive prompt
        # Accept both comma-separated and space-separated node lists
        nodes = re.split(r"[,\s]+", cli_pve_nodes.strip())
        names = (
            re.split(r"[,\s]+", cli_pve_names.strip())
            if cli_pve_names
            else [f"pve{i + 1:02d}" for i in range(len(nodes))]
        )
        while len(names) < len(nodes):
            names.append(f"pve{len(names) + 1:02d}")
        invalid_nodes = _invalid_ip_values(nodes)
        if invalid_nodes:
            fmt.step_fail(f"Invalid PVE node IP(s) from CLI: {', '.join(invalid_nodes)}")
        else:
            content = _update_toml_value(content, "nodes", nodes)
            content = _update_toml_value(content, "node_names", names)
            cfg.pve_nodes = nodes
            cfg.pve_node_names = names
            changed = True
            fmt.step_ok(f"PVE nodes (from CLI): {', '.join(nodes)}")
    elif cfg.pve_nodes:
        fmt.step_ok(f"PVE nodes already configured: {', '.join(cfg.pve_nodes)}")
        if not headless and not yes_flag and _confirm("Reconfigure PVE nodes?"):
            cfg.pve_nodes = []  # force re-prompt below
        # else keep existing

    if not cfg.pve_nodes and not cli_pve_nodes and headless:
        fmt.step_warn("No PVE nodes configured — use --pve-nodes in headless mode")
    elif not cfg.pve_nodes and not cli_pve_nodes:
        fmt.line(f"  {fmt.C.DIM}Enter your Proxmox VE node IPs (space-separated).{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Example: 192.168.1.10 192.168.1.11 192.168.1.12{fmt.C.RESET}")
        node_input = _input("PVE node IPs")
        if node_input:
            nodes = node_input.split()
            invalid_nodes = _invalid_ip_values(nodes)
            if invalid_nodes:
                fmt.step_fail(f"Invalid PVE node IP(s): {', '.join(invalid_nodes)}")
                nodes = []
        if node_input and nodes:
            # Ask for node names
            fmt.line(f"  {fmt.C.DIM}Enter names for each node (space-separated, same order).{fmt.C.RESET}")
            name_default = " ".join(f"pve{i + 1:02d}" for i in range(len(nodes)))
            name_input = _input("Node names", name_default)
            names = name_input.split()
            # Pad names if fewer than nodes
            while len(names) < len(nodes):
                names.append(f"pve{len(names) + 1:02d}")

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
                            next_section = re.search(r"^\[(?!pve\.)", content[pve_section + 5 :], re.MULTILINE)
                            if next_section:
                                insert_at = pve_section + 5 + next_section.start()
                            else:
                                insert_at = len(content)
                            storage_block = f'\n{section}\npool = "{pool}"\ntype = "SSD"\n\n'
                            content = content[:insert_at] + storage_block + content[insert_at:]
                            changed = True
                    else:
                        # Section exists, update the pool value
                        section_pos = content.find(section)
                        pool_pattern = re.compile(
                            r"^(pool\s*=\s*).*$",
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
        if not _val.ip(cli_gateway):
            fmt.step_fail(f"Invalid gateway IP from CLI: {cli_gateway}")
        else:
            content = _update_toml_value(content, "gateway", cli_gateway)
            cfg.vm_gateway = cli_gateway
            changed = True
            fmt.step_ok(f"Gateway (from CLI): {cli_gateway}")
    elif cfg.vm_gateway:
        fmt.step_ok(f"Gateway: {cfg.vm_gateway}")
    elif headless:
        # Auto-derive gateway from first PVE node IP (.1 on same subnet)
        if cfg.pve_nodes:
            parts = cfg.pve_nodes[0].rsplit(".", 1)
            auto_gw = f"{parts[0]}.1" if len(parts) == 2 else ""
            if auto_gw and _val.ip(auto_gw):
                content = _update_toml_value(content, "gateway", auto_gw)
                cfg.vm_gateway = auto_gw
                changed = True
                fmt.step_ok(f"Gateway: {auto_gw} (auto-derived from PVE node)")
            else:
                fmt.step_warn("No gateway set — could not auto-derive from PVE nodes")
        else:
            fmt.step_warn("No gateway set — no PVE nodes to derive from")
    else:
        fmt.line(f"  {fmt.C.DIM}Your network gateway IP (for VM networking).{fmt.C.RESET}")
        gw = _input("Gateway IP")
        if gw:
            if not _val.ip(gw):
                fmt.step_fail(f"Invalid gateway IP: {gw}")
            else:
                content = _update_toml_value(content, "gateway", gw)
                cfg.vm_gateway = gw
                changed = True
                fmt.step_ok(f"Gateway: {gw}")
        else:
            fmt.step_warn("No gateway set — VM networking may not work")

    # ── Nameserver ──
    if cli_nameserver:
        if not _val.ip(cli_nameserver):
            fmt.step_fail(f"Invalid nameserver IP from CLI: {cli_nameserver}")
        else:
            content = _update_toml_value(content, "nameserver", cli_nameserver)
            cfg.vm_nameserver = cli_nameserver
            changed = True
            fmt.step_ok(f"Nameserver (from CLI): {cli_nameserver}")
    elif cfg.vm_nameserver and cfg.vm_nameserver != "1.1.1.1":
        fmt.step_ok(f"Nameserver: {cfg.vm_nameserver}")
    elif headless:
        ns = cfg.vm_nameserver or "1.1.1.1"
        fmt.step_ok(f"Nameserver: {ns} (default)")
    else:
        ns = _input("DNS nameserver", cfg.vm_nameserver or "1.1.1.1")
        if ns != (cfg.vm_nameserver or "1.1.1.1"):
            if not _val.ip(ns):
                fmt.step_fail(f"Invalid nameserver IP: {ns}")
            else:
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
    elif not headless:
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
    elif headless:
        mode = cfg.ssh_mode or "sudo"
        fmt.step_ok(f"SSH mode: {mode}")
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

    logger.info("init_phase_complete: Phase 2 - configure", phase=2, pve_nodes=len(cfg.pve_nodes))


# ── VLAN Discovery (Phase 2 supplement) ───────────────────────────


def _parse_network_interfaces(text):
    """Parse Debian /etc/network/interfaces for VLAN information.

    Handles two PVE network config styles:
    1. VLAN subinterfaces: iface vmbr0.100 inet static
    2. Bridge-VLAN-aware: bridge-vids 5 10 25 2550

    Returns list of dicts: [{vlan_id, bridge, address, prefix, gateway, name}]
    """
    vlans = {}  # vlan_id -> {bridge, address, prefix, gateway}
    current_iface = None

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Match iface declarations: "iface vmbr0.100 inet static"
        if line.startswith("iface "):
            parts = line.split()
            if len(parts) >= 2:
                iface_name = parts[1]
                current_iface = iface_name

                # Check for VLAN subinterface pattern: vmbr0.100
                if "." in iface_name:
                    base, vid_str = iface_name.rsplit(".", 1)
                    try:
                        vid = int(vid_str)
                        if 1 <= vid <= 4094:
                            vlans.setdefault(vid, {"bridge": base, "address": "", "prefix": "", "gateway": ""})
                    except ValueError:
                        pass

        # Match address lines: "address 10.25.255.50/24"
        elif line.startswith("address ") and current_iface:
            addr = line.split(None, 1)[1].strip()
            # Apply to VLAN if this iface is a VLAN subinterface
            if "." in current_iface:
                _, vid_str = current_iface.rsplit(".", 1)
                try:
                    vid = int(vid_str)
                    if vid in vlans:
                        vlans[vid]["address"] = addr
                        # Derive prefix from CIDR
                        ip_part = addr.split("/")[0]
                        octets = ip_part.rsplit(".", 1)
                        if len(octets) == 2:
                            vlans[vid]["prefix"] = octets[0]
                except ValueError:
                    pass

        # Match gateway lines: "gateway 10.25.255.1"
        elif line.startswith("gateway ") and current_iface:
            gw = line.split(None, 1)[1].strip()
            if "." in current_iface:
                _, vid_str = current_iface.rsplit(".", 1)
                try:
                    vid = int(vid_str)
                    if vid in vlans:
                        vlans[vid]["gateway"] = gw
                except ValueError:
                    pass

        # Match bridge-vids (VLAN-aware bridge): "bridge-vids 5 10 25 2550"
        # NOTE: "bridge-vids 2-4094" is PVE's default "allow all VLANs" —
        # NOT actual VLAN definitions. Skip ranges > 100 VLANs wide.
        elif line.startswith("bridge-vids "):
            vid_strs = line.split()[1:]
            bridge = current_iface or "vmbr0"
            for vs in vid_strs:
                if "-" in vs:
                    try:
                        lo, hi = vs.split("-", 1)
                        lo_i, hi_i = int(lo), int(hi)
                        if (hi_i - lo_i) > 100:
                            continue  # Skip "2-4094" style allow-all ranges
                        for vid in range(lo_i, hi_i + 1):
                            vlans.setdefault(vid, {"bridge": bridge, "address": "", "prefix": "", "gateway": ""})
                    except ValueError:
                        pass
                else:
                    try:
                        vid = int(vs)
                        if 1 <= vid <= 4094:
                            vlans.setdefault(vid, {"bridge": bridge, "address": "", "prefix": "", "gateway": ""})
                    except ValueError:
                        pass

    # Also extract the base bridge address (VLAN 0 / native LAN)
    # Re-scan for non-VLAN ifaces with addresses
    current_iface = None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("iface "):
            parts = line.split()
            current_iface = parts[1] if len(parts) >= 2 else None
        elif line.startswith("address ") and current_iface and "." not in current_iface:
            # Non-VLAN interface address — this is the native/mgmt network
            addr = line.split(None, 1)[1].strip()
            ip_part = addr.split("/")[0]
            octets = ip_part.rsplit(".", 1)
            if len(octets) == 2 and current_iface.startswith("vmbr"):
                # Infer subnet for bridge-vids that lack their own addresses
                pass  # We can't derive VLAN subnets from the bridge address alone

    # Only return VLANs that have actual addresses — skip bridge-vids placeholders
    return [
        {
            "vlan_id": vid,
            "bridge": info["bridge"],
            "address": info["address"],
            "prefix": info["prefix"],
            "gateway": info["gateway"],
            "name": f"VLAN{vid}",
        }
        for vid, info in sorted(vlans.items())
        if info["address"] or info["prefix"]
    ]


def _collect_bootstrap_auth(cfg, ctx, args=None):
    """Collect bootstrap SSH credentials for PVE access.

    Stores in ctx for reuse by Phase 5 (PVE deploy) and VLAN discovery.
    Returns True if credentials were collected.
    """
    # Check CLI flags first
    bootstrap_key = getattr(args, "bootstrap_key", None) if args else None
    bootstrap_user = getattr(args, "bootstrap_user", None) if args else None
    bootstrap_pass_file = getattr(args, "bootstrap_password_file", None) if args else None

    if bootstrap_key and os.path.isfile(bootstrap_key):
        ctx["bootstrap_key"] = bootstrap_key
        ctx["bootstrap_user"] = bootstrap_user or "root"
        ctx["bootstrap_pass"] = ""
        fmt.step_ok(f"Bootstrap auth: {ctx['bootstrap_user']} via key {bootstrap_key}")
        return True

    if bootstrap_pass_file and os.path.isfile(bootstrap_pass_file):
        with open(bootstrap_pass_file) as f:
            ctx["bootstrap_pass"] = f.read().strip()
        ctx["bootstrap_user"] = bootstrap_user or "root"
        ctx["bootstrap_key"] = ""
        fmt.step_ok(f"Bootstrap auth: {ctx['bootstrap_user']} via password file")
        return True

    if not cfg.pve_nodes:
        return False

    # Interactive prompt
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Bootstrap authentication for PVE nodes{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}Needed to deploy service account and discover VLANs.{fmt.C.RESET}")
    fmt.blank()

    pve_user = _input("Deploy as user (root or sudo account)", "root")
    ctx["bootstrap_user"] = pve_user

    fmt.line(f"  {fmt.C.DIM}How to authenticate to PVE nodes as '{pve_user}'?{fmt.C.RESET}")
    fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Password")
    fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
    fmt.blank()

    auth_choice = _input("Choice", "A").upper()

    if auth_choice == "B":
        key_path = _input("SSH key path", os.path.expanduser("~/.ssh/id_ed25519"))
        if os.path.isfile(key_path):
            ctx["bootstrap_key"] = key_path
            ctx["bootstrap_pass"] = ""
            fmt.step_ok(f"Using SSH key: {key_path}")
            return True
        fmt.step_warn(f"Key not found: {key_path} — falling back to password")

    # Password auth
    rc, _, _ = _run(["which", "sshpass"])
    if rc != 0:
        fmt.step_fail("'sshpass' not installed — required for password-based SSH")
        from freq.core.packages import install_hint
        fmt.line(f"  {fmt.C.DIM}Install with: {install_hint('sshpass')}{fmt.C.RESET}")
        ctx["bootstrap_key"] = ""
        ctx["bootstrap_pass"] = ""
        return False

    auth_pass = getpass.getpass(
        f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for '{pve_user}' on PVE nodes: "
    )
    ctx["bootstrap_pass"] = auth_pass
    ctx["bootstrap_key"] = ""
    return True


def _discover_vlans_from_pve(cfg, ctx):
    """SSH to a PVE node and discover VLANs from network configuration.

    Parses /etc/network/interfaces for VLAN subinterfaces and bridge-vids.
    Supplements with `ip -j addr show` for live interface data.
    Writes vlans.toml with discovered VLANs.
    """
    if not cfg.pve_nodes:
        return

    # Determine SSH method: bootstrap creds or service account key
    key_path = ctx.get("key_path", "") or cfg.ssh_key_path
    svc_name = ctx.get("svc_name", cfg.ssh_service_account)
    bootstrap_key = ctx.get("bootstrap_key", "")
    bootstrap_pass = ctx.get("bootstrap_pass", "")
    bootstrap_user = ctx.get("bootstrap_user", "root")

    # Choose auth method
    use_bootstrap = bool(bootstrap_key or bootstrap_pass)
    if use_bootstrap:
        ssh_user = bootstrap_user
        ssh_key = bootstrap_key
        ssh_pass = bootstrap_pass
    elif key_path and os.path.isfile(key_path):
        ssh_user = svc_name
        ssh_key = key_path
        ssh_pass = ""
    else:
        fmt.step_warn("No SSH credentials available — skipping VLAN discovery")
        return

    fmt.step_start("Discovering VLANs from PVE network config...")

    # Try each PVE node until one responds
    iface_text = ""
    ip_json = ""
    for node_ip in cfg.pve_nodes:
        # Build SSH command
        ssh_opts = ["-n", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]

        if ssh_key:
            ssh_cmd = ["ssh"] + ssh_opts + ["-o", "BatchMode=yes", "-i", ssh_key, f"{ssh_user}@{node_ip}"]
        elif ssh_pass:
            ssh_cmd = ["sshpass", "-p", ssh_pass, "ssh"] + ssh_opts + [f"{ssh_user}@{node_ip}"]
        else:
            continue

        # Read network interfaces config
        cmd_ifaces = "cat /etc/network/interfaces /etc/network/interfaces.d/* 2>/dev/null"
        if ssh_user != "root":
            cmd_ifaces = f"sudo {cmd_ifaces}"
        rc, out, _ = _run(ssh_cmd + [cmd_ifaces], timeout=DEFAULT_CMD_TIMEOUT)
        if rc == 0 and out.strip():
            iface_text = out
            # Also get live interface data for address info
            cmd_ip = "ip -j addr show 2>/dev/null"
            if ssh_user != "root":
                cmd_ip = f"sudo {cmd_ip}"
            rc2, out2, _ = _run(ssh_cmd + [cmd_ip], timeout=DEFAULT_CMD_TIMEOUT)
            if rc2 == 0:
                ip_json = out2
            break

    if not iface_text:
        fmt.step_warn("Could not read network config from any PVE node")
        return

    # Parse interfaces file
    parsed_vlans = _parse_network_interfaces(iface_text)

    if not parsed_vlans:
        fmt.step_warn("No VLANs found in PVE network configuration")
        return

    # Supplement with live IP data to fill in missing addresses
    if ip_json:
        import json as _json
        try:
            ip_data = _json.loads(ip_json)
            # Build map of iface name -> first IPv4 address
            live_addrs = {}
            for iface in ip_data:
                ifname = iface.get("ifname", "")
                for ai in iface.get("addr_info", []):
                    if ai.get("family") == "inet" and not ai.get("local", "").startswith("127."):
                        live_addrs[ifname] = f"{ai['local']}/{ai.get('prefixlen', 24)}"
                        break

            # Fill in missing addresses from live data
            for v in parsed_vlans:
                if not v["address"]:
                    # Look for matching interface name
                    vid = v["vlan_id"]
                    bridge = v["bridge"]
                    candidates = [f"{bridge}.{vid}", f"vlan{vid}"]
                    for cand in candidates:
                        if cand in live_addrs:
                            v["address"] = live_addrs[cand]
                            ip_part = live_addrs[cand].split("/")[0]
                            octets = ip_part.rsplit(".", 1)
                            if len(octets) == 2:
                                v["prefix"] = octets[0]
                            break
        except (_json.JSONDecodeError, ValueError, KeyError):
            pass

    # Write vlans.toml
    vlans_path = os.path.join(cfg.conf_dir, "vlans.toml")
    try:
        lines = [
            "# FREQ VLAN Definitions",
            "# Auto-discovered from PVE network configuration",
            "",
        ]
        for v in parsed_vlans:
            # Generate a human-friendly name
            vlan_key = f"vlan{v['vlan_id']}"
            lines.append(f"[vlan.{vlan_key}]")
            lines.append(f"id = {v['vlan_id']}")
            lines.append(f'name = "{v["name"]}"')
            if v["address"]:
                # Derive subnet from address
                ip_part, cidr = v["address"].split("/") if "/" in v["address"] else (v["address"], "24")
                octets = ip_part.rsplit(".", 1)
                prefix = octets[0] if len(octets) == 2 else ip_part
                lines.append(f'subnet = "{prefix}.0/{cidr}"')
                lines.append(f'prefix = "{prefix}"')
            elif v["prefix"]:
                lines.append(f'subnet = "{v["prefix"]}.0/24"')
                lines.append(f'prefix = "{v["prefix"]}"')
            if v["gateway"]:
                lines.append(f'gateway = "{v["gateway"]}"')
            lines.append("")

        with open(vlans_path, "w") as f:
            f.write("\n".join(lines))

        fmt.step_ok(f"Discovered {len(parsed_vlans)} VLANs — written to vlans.toml")

        # Reload VLANs into config
        try:
            from freq.core.config import load_vlans
            cfg.vlans = load_vlans(vlans_path)
        except Exception:
            pass

    except OSError as e:
        fmt.step_warn(f"Could not write vlans.toml: {e}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Service Account
# ═══════════════════════════════════════════════════════════════════


def _phase_service_account(cfg, ctx, args=None):
    """Create service account with NOPASSWD sudo."""
    logger.info("init_phase_start: Phase 3 - service_account", phase=3)
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
            if len(file_pass) < 8:
                fmt.step_fail("Password too short (min 8 characters)")
                return False
            fmt.step_ok(f"Password loaded from {pw_file}")
        else:
            fmt.step_fail(f"Password file not found: {pw_file}")
            return False

    # Check if account exists
    rc, _, _ = _run(["id", svc_name])
    if rc == 0:
        fmt.step_ok(f"Account '{svc_name}' already exists")
        # Check sudo — verify sudoers file exists (don't rely on sudo -u from root)
        rc2, _, _ = _run(["test", "-f", f"/etc/sudoers.d/freq-{svc_name}"])
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
        p = subprocess.Popen(
            ["/usr/sbin/chpasswd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
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

    logger.info("init_phase_complete: Phase 3 - service_account", phase=3, user=svc_name)
    audit.record("create_service_account", "local", "success", user=svc_name)
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
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".freq-auth", delete=False)
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
    logger.info("init_phase_start: Phase 4 - ssh_keys", phase=4)
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
        rc, _, err = _run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-C",
                f"freq@{hostname}",
                "-f",
                ed_key,
                "-N",
                "",
                "-q",
            ]
        )
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
        rc, _, err = _run(
            [
                "ssh-keygen",
                "-t",
                "rsa",
                "-b",
                "4096",
                "-C",
                f"freq-legacy@{hostname}",
                "-f",
                rsa_key,
                "-N",
                "",
                "-q",
            ]
        )
        if rc == 0:
            os.chmod(rsa_key, 0o600)
            os.chmod(f"{rsa_key}.pub", 0o644)
            fmt.step_ok("FREQ RSA-4096 key generated (for iDRAC + switch)")
        else:
            fmt.step_warn(f"RSA key generation failed: {err[:60]} — iDRAC/switch will need manual setup")

    ctx["key_path"] = ed_key
    ctx["rsa_key_path"] = rsa_key

    # Fix ownership — init runs as root but keys need to be readable by
    # the service account that runs the dashboard.
    svc_name = ctx["svc_name"]
    for f in [key_dir, ed_key, f"{ed_key}.pub", rsa_key, f"{rsa_key}.pub"]:
        if os.path.exists(f):
            _chown(f"{svc_name}:{svc_name}", f)
    fmt.step_ok(f"Key ownership set to {svc_name}")

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
        _chown(f"{svc_name}:{svc_name}", ssh_dir)

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
            _chown(f"{svc_name}:{svc_name}", auth_keys)
            fmt.step_ok(f"ed25519 public key deployed to local {svc_name}")

    # Also copy keys to service account's .ssh for outbound SSH
    if rc == 0 and ctx.get("key_path"):
        import shutil

        svc_ssh = os.path.join(svc_home, ".ssh")

        # ed25519 (primary)
        svc_ed = os.path.join(svc_ssh, "id_ed25519")
        shutil.copy2(ctx["key_path"], svc_ed)
        shutil.copy2(f"{ctx['key_path']}.pub", f"{svc_ed}.pub")
        os.chmod(svc_ed, 0o600)
        _chown(f"{svc_name}:{svc_name}", svc_ed, f"{svc_ed}.pub")
        ctx["key_path"] = svc_ed
        cfg.ssh_key_path = svc_ed  # Keep cfg in sync for phases that read cfg directly
        fmt.step_ok(f"ed25519 private key synced to {svc_name}/.ssh/")

        # RSA (legacy)
        if os.path.isfile(rsa_key):
            svc_rsa = os.path.join(svc_ssh, "id_rsa")
            shutil.copy2(rsa_key, svc_rsa)
            shutil.copy2(f"{rsa_key}.pub", f"{svc_rsa}.pub")
            os.chmod(svc_rsa, 0o600)
            _chown(f"{svc_name}:{svc_name}", svc_rsa, f"{svc_rsa}.pub")
            ctx["rsa_key_path"] = svc_rsa
            cfg.ssh_rsa_key_path = svc_rsa  # Keep cfg in sync
            fmt.step_ok(f"RSA private key synced to {svc_name}/.ssh/")

    # RSA key status for legacy devices
    if os.path.isfile(rsa_pub):
        fmt.step_ok("RSA key ready for automated iDRAC/switch deployment")

    logger.info("init_phase_complete: Phase 4 - ssh_keys", phase=4)
    audit.record("generate_keys", "local", "success", key_type="ed25519+rsa")


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: PVE Node Deployment
# ═══════════════════════════════════════════════════════════════════


def _phase_pve_deploy(cfg, ctx, args=None):
    """Deploy service account + key to PVE nodes."""
    logger.info("init_phase_start: Phase 5 - pve_deploy", phase=5)
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

    # Reuse bootstrap credentials collected in Phase 2
    auth_key = ctx.get("bootstrap_key", "")
    auth_pass = ctx.get("bootstrap_pass", "")
    pve_user = ctx.get("bootstrap_user", "root")

    # Fallback: check CLI flags if ctx doesn't have creds
    if not auth_key and not auth_pass:
        bootstrap_key = getattr(args, "bootstrap_key", None) if args else None
        bootstrap_pass_file = getattr(args, "bootstrap_password_file", None) if args else None
        bootstrap_user = getattr(args, "bootstrap_user", None) if args else None

        if bootstrap_key and os.path.isfile(bootstrap_key):
            auth_key = bootstrap_key
            pve_user = bootstrap_user or "root"
        elif bootstrap_pass_file and os.path.isfile(bootstrap_pass_file):
            with open(bootstrap_pass_file) as f:
                auth_pass = f.read().strip()
            pve_user = bootstrap_user or "root"

    # Last resort: interactive prompt
    if not auth_key and not auth_pass:
        pve_user = _input("Deploy as user (root or sudo account)", "root")
        fmt.line(f"  {fmt.C.DIM}How to authenticate to PVE nodes as '{pve_user}'?{fmt.C.RESET}")
        fmt.line(f"    {fmt.C.BOLD}A{fmt.C.RESET}) Password")
        fmt.line(f"    {fmt.C.BOLD}B{fmt.C.RESET}) Existing SSH key")
        fmt.blank()

        auth_choice = _input("Choice", "A").upper()
        if auth_choice == "B":
            auth_key = _input("SSH key path", os.path.expanduser("~/.ssh/id_ed25519"))
            if not os.path.isfile(auth_key):
                fmt.step_warn(f"Key not found: {auth_key} — falling back to password")
                auth_key = ""
        if not auth_key:
            rc, _, _ = _run(["which", "sshpass"])
            if rc != 0:
                fmt.step_fail("'sshpass' not installed — required for password-based SSH")
                return
            auth_pass = getpass.getpass(
                f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for '{pve_user}' on PVE nodes: "
            )

    fmt.step_ok(f"Bootstrap auth: {pve_user} via {'key' if auth_key else 'password'}")

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
    logger.info("init_phase_complete: Phase 5 - pve_deploy", phase=5, ok=ok, fail=fail)


# ═══════════════════════════════════════════════════════════════════
# PHASE 6: PVE API Token
# ═══════════════════════════════════════════════════════════════════


def _phase_pve_api_token(cfg, ctx):
    """Create a FREQ-specific PVE API token for dashboard metrics.

    Creates freq-ops@pam user with PVEAuditor+PVEVMUser roles,
    generates an API token, saves the secret to a credential file,
    and updates freq.toml so the dashboard can pull live PVE metrics.
    """
    logger.info("init_phase_start: Phase 6 - pve_api_token", phase=6)
    import json as _json

    pve_nodes = cfg.pve_nodes
    if not pve_nodes:
        fmt.step_warn("No PVE nodes configured — skipping API token creation")
        return

    key_path = ctx.get("key_path", "") or cfg.ssh_key_path
    svc_name = ctx.get("svc_name", cfg.ssh_service_account)

    if not key_path or not os.path.isfile(key_path):
        fmt.step_warn("SSH key not available — skipping API token creation")
        return

    # Find first reachable PVE node
    first_node = None
    for ip in pve_nodes:
        rc, _, _ = _run(
            ["ssh", "-n", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
             "-i", key_path, f"{svc_name}@{ip}", "echo ok"],
            timeout=QUICK_CHECK_TIMEOUT,
        )
        if rc == 0:
            first_node = ip
            break

    if not first_node:
        fmt.step_warn("No PVE nodes reachable via service account key — skipping API token")
        return

    ssh_base = [
        "ssh", "-n",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-i", key_path,
        f"{svc_name}@{first_node}",
    ]

    # Step 1: Check if freq-ops@pam user already exists
    fmt.step_start("Checking for existing FREQ API user...")
    rc, out, _ = _run(ssh_base + ["sudo pveum user list --output-format json 2>/dev/null"])
    user_exists = "freq-ops@pam" in out if rc == 0 else False

    if not user_exists:
        # Create freq-ops@pam user
        fmt.step_start("Creating freq-ops@pam user on PVE...")
        rc, _, err = _run(ssh_base + ["sudo pveum user add freq-ops@pam --comment 'FREQ API access'"])
        if rc != 0:
            fmt.step_fail(f"Failed to create freq-ops@pam: {err.strip()[:200]}")
            return
        fmt.step_ok("Created freq-ops@pam user")

        # Grant roles
        rc, _, err = _run(
            ssh_base + ["sudo pveum acl modify / --roles PVEAuditor,PVEVMUser --users freq-ops@pam"]
        )
        if rc != 0:
            fmt.step_warn(f"Failed to set roles: {err.strip()[:200]}")
    else:
        fmt.step_ok("freq-ops@pam user already exists")

    # Step 2: Create API token (delete+recreate to get secret)
    fmt.step_start("Creating API token freq-ops@pam!freq-rw...")
    rc, out, err = _run(
        ssh_base + [
            "sudo pveum user token add freq-ops@pam freq-rw"
            " --privsep 0 --output-format json 2>&1"
        ]
    )
    if rc != 0 and "already exists" in (err + out):
        # Token exists — delete and recreate to get the secret
        _run(ssh_base + ["sudo pveum user token remove freq-ops@pam freq-rw"])
        rc, out, err = _run(
            ssh_base + [
                "sudo pveum user token add freq-ops@pam freq-rw"
                " --privsep 0 --output-format json 2>&1"
            ]
        )
    if rc != 0:
        fmt.step_fail(f"Failed to create API token: {(err + out).strip()[:200]}")
        return

    # Parse token output
    token_id = "freq-ops@pam!freq-rw"
    token_secret = ""
    try:
        token_data = _json.loads(out)
        token_id = token_data.get("full-tokenid", token_id)
        token_secret = token_data.get("value", "")
    except (_json.JSONDecodeError, ValueError):
        # Fallback: plain text parse
        for line in out.split("\n"):
            if "value" in line.lower() and ":" in line:
                token_secret = line.split(":", 1)[1].strip().strip('"')
                break

    if not token_secret:
        fmt.step_fail("Token created but no secret returned")
        return

    fmt.step_ok(f"Token created: {token_id}")

    # Step 3: Save token secret to credential file
    svc_name = ctx["svc_name"]
    cred_dir = os.path.join(os.path.dirname(cfg.conf_dir), "credentials")
    os.makedirs(cred_dir, mode=0o700, exist_ok=True)
    cred_path = os.path.join(cred_dir, "pve-token-rw")
    try:
        with open(cred_path, "w") as f:
            f.write(token_secret)
        os.chmod(cred_path, 0o600)
        # Dashboard runs as svc_name — must be able to read token
        _chown(f"{svc_name}:{svc_name}", cred_dir, recursive=True)
        fmt.step_ok(f"Token secret saved to {cred_path}")
    except OSError as e:
        fmt.step_fail(f"Failed to save token secret: {e}")
        return

    # Step 4: Update freq.toml
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    try:
        with open(toml_path) as f:
            content = f.read()
        content = _update_toml_value(content, "api_token_id", token_id)
        content = _update_toml_value(content, "api_token_secret_path", cred_path)
        with open(toml_path, "w") as f:
            f.write(content)
        fmt.step_ok("freq.toml updated with PVE API token")
    except OSError as e:
        fmt.step_warn(f"Could not update freq.toml: {e}")

    # Step 5: Update cfg in-memory for subsequent phases
    cfg.pve_api_token_id = token_id
    cfg.pve_api_token_secret = token_secret

    # Step 6: Verify token works via REST API
    fmt.step_start("Verifying PVE API token...")
    ctx["api_token_verified"] = False
    try:
        from freq.modules.pve import _pve_api_call
        result, ok = _pve_api_call(cfg, first_node, "/version")
        if ok:
            ver = result.get("version", "unknown") if isinstance(result, dict) else "unknown"
            fmt.step_ok(f"PVE REST API verified (PVE {ver})")
            ctx["api_token_verified"] = True
        else:
            fmt.step_warn("Token saved but API test failed — will fall back to SSH")
    except Exception as e:
        fmt.step_warn(f"API verification error: {e} — will fall back to SSH")

    logger.info("init_phase_complete: Phase 6 - pve_api_token", phase=6)
    audit.record("create_api_token", first_node, "success")


# ═══════════════════════════════════════════════════════════════════
# Fleet Host Discovery + Deployment Helpers
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

    from freq.core.config import Host, append_host_toml

    host = Host(ip=ip, label=label, htype=htype, groups=groups)
    append_host_toml(cfg.hosts_file, host)
    cfg.hosts.append(host)

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
    known_labels = {h.label.lower() for h in cfg.hosts}
    ssh_reachable = sum(1 for h in hosts_info if h["reachable"])
    new_count = _display_discovery_results(alive, hosts_info, known_ips)

    if new_count == 0:
        fmt.blank()
        if ssh_reachable == 0:
            svc = cfg.ssh_service_account or "freq-admin"
            fmt.line(f"  {fmt.C.YELLOW}No hosts could be identified via SSH.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Tried connecting as '{svc}'. Hosts need this account + key first.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Use 'freq host add' to register hosts manually, then deploy keys.{fmt.C.RESET}")
        else:
            fmt.line(f"  {fmt.C.GREEN}All discovered hosts are already registered.{fmt.C.RESET}")
        return

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}{new_count} new host(s) found.{fmt.C.RESET}")
    fmt.blank()

    # Offer to register discovered hosts
    from freq.core.config import Host

    for h in hosts_info:
        if h["ip"] in known_ips:
            continue

        hostname = h["hostname"] or ""
        detected_type = h["type"] if h["reachable"] else "unknown"

        if not h["reachable"]:
            # Ping-only host — offer manual registration (pfSense, TrueNAS, BMCs)
            fmt.line(
                f"  {fmt.C.YELLOW}{h['ip']}{fmt.C.RESET} — ping only "
                f"(could not SSH — pfSense/TrueNAS/BMC?)"
            )
            if not _confirm(f"  Register this host manually?", default=False):
                continue
            hostname = _input(f"    Hostname/label")
            if not hostname:
                continue
            detected_type = _input(f"    Type (pfsense/truenas/idrac/switch/linux)", "linux")

        # Check if same host already registered under different VLAN IP
        if hostname and hostname.lower() in known_labels:
            fmt.line(
                f"  {fmt.C.YELLOW}⚠{fmt.C.RESET} {h['ip']} — {hostname} "
                f"[{detected_type}] — hostname already registered (different VLAN?), skipping"
            )
            continue

        fmt.line(f"  {fmt.C.CYAN}{h['ip']}{fmt.C.RESET} — {hostname} [{detected_type}]")
        if not _confirm(f"  Register this host?", default=True):
            continue

        label = _input(f"    Label", hostname)
        if label.lower() in known_labels:
            fmt.step_warn(f"Label '{label}' already in use — skipping")
            continue
        htype = _input(f"    Type", detected_type)
        groups = _input(f"    Groups (optional)", "")

        from freq.core.config import append_host_toml

        host = Host(ip=h["ip"], label=label, htype=htype, groups=groups)
        append_host_toml(cfg.hosts_file, host)
        cfg.hosts.append(host)
        known_ips.add(h["ip"])
        known_labels.add(label.lower())
        fmt.step_ok(f"Registered: {label} ({h['ip']}) [{htype}]")

    # Offer to scan another subnet
    fmt.blank()
    if _confirm("Scan another subnet?"):
        _discover_and_register(cfg, ctx)


# ═══════════════════════════════════════════════════════════════════
# PHASE 10: PDM Setup (detect / install / configure)
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
    rc, _, err = _run(
        [
            "wget",
            "-qO",
            "/etc/apt/trusted.gpg.d/proxmox-release-trixie.gpg",
            "https://enterprise.proxmox.com/debian/proxmox-release-trixie.gpg",
        ],
        timeout=30,
    )
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
    rc, _, err = _run(
        [
            "apt-get",
            "install",
            "-y",
            "proxmox-datacenter-manager",
        ],
        timeout=600,
    )
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
    ok, result, set_cookie = _pdm_api_request(
        "POST",
        "/api2/json/access/ticket",
        {
            "username": "root@pam",
            "password": password,
        },
    )
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
    ok, result, _ = _pdm_api_request(
        "POST",
        "/api2/json/pve/probe-tls",
        {
            "hostname": ip,
        },
        cookies=cookies,
        csrf_token=csrf,
    )
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
    ok, result, _ = _pdm_api_request("POST", "/api2/json/remotes/remote", data, cookies=cookies, csrf_token=csrf)
    return ok


def _pdm_create_pve_token(pve_ip, ctx):
    """Create pdm@pve user and API token on a PVE node via SSH.

    Uses the already-deployed freq service account for SSH access.
    Returns (token_id, token_secret) or (None, None).
    """
    key_path = ctx.get("key_path", "")
    svc_name = ctx.get("svc_name", cfg.ssh_service_account if hasattr(cfg, "ssh_service_account") else "freq-admin")

    ssh_base = [
        "ssh",
        "-n",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "BatchMode=yes",
        "-i",
        key_path,
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
    logger.info("init_phase_start: Phase 10 - pdm", phase=10)
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
        fmt.line(
            f"  {fmt.C.DIM}Create manually: pveum user add pdm@pve && pveum user token add pdm@pve pdm --privsep 0{fmt.C.RESET}"
        )
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
        fmt.line(
            f"  {fmt.C.GREEN}PDM configured!{fmt.C.RESET} Dashboard: {fmt.C.CYAN}https://localhost:8443{fmt.C.RESET}"
        )
    else:
        fmt.step_fail(f"Failed to add remote '{remote_name}'")
        fmt.line(f"  {fmt.C.DIM}The remote may already exist. Check: https://localhost:8443{fmt.C.RESET}")

    logger.info("init_phase_complete: Phase 10 - pdm", phase=10)


# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Fleet Discovery
# ═══════════════════════════════════════════════════════════════════


def _is_docker_bridge_ip(ip):
    """Return True if ip looks like a Docker bridge address (172.17-31.x.x)."""
    if not ip.startswith("172."):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        second = int(parts[1])
        return 17 <= second <= 31
    except ValueError:
        return False


def _classify_host_by_name(name):
    """Auto-classify host type from VM/hostname. Returns htype string.

    Order matters: more specific patterns (idrac, switch) before generic (pve).
    """
    name_lower = name.lower()
    # Device types first (most specific)
    if "idrac" in name_lower or "ilo" in name_lower or "bmc" in name_lower:
        return "idrac"
    if "switch" in name_lower or "cisco" in name_lower:
        return "switch"
    if "pfsense" in name_lower or "opnsense" in name_lower:
        return "pfsense"
    if "truenas" in name_lower or "freenas" in name_lower or "nexus" in name_lower:
        return "truenas"
    # NAS-like hostnames (standalone "nas" as whole name or hyphen-delimited segment)
    if name_lower == "nas" or name_lower.startswith("nas-") or "-nas-" in name_lower or name_lower.endswith("-nas"):
        return "truenas"
    # Docker before PVE (a "pve-docker" host is a docker host)
    if any(k in name_lower for k in ("docker", "plex", "arr", "qbit", "tdarr", "sabnzbd", "portainer")):
        return "docker"
    if "pve" in name_lower or "proxmox" in name_lower:
        return "pve"
    return "linux"


def _phase_fleet_discover(cfg, ctx, args=None):
    """Discover all fleet hosts via PVE API + multi-VLAN sweep.

    Step 1: Query PVE API for all VMs/CTs, get IPs via guest agent.
    Step 2: Scan all VLANs for additional hosts (physical devices, bare-metal).
    Step 3: Auto-detect infrastructure devices (firewall, NAS, switch).
    Step 4: Write hosts.toml with discovered fleet.
    Step 5: Write fleet-boundaries.toml with physical devices + PVE nodes.
    Step 6: Update freq.toml [infrastructure] with detected IPs.
    """
    logger.info("init_phase_start: Phase 7 - fleet_discover", phase=7)
    import json as _json

    from freq.core.config import Host, append_host_toml

    key_path = ctx.get("key_path", "") or cfg.ssh_key_path
    svc_name = ctx.get("svc_name", cfg.ssh_service_account)
    hosts_file_arg = getattr(args, "hosts_file", None) if args else None
    scoped_hosts = []

    if hosts_file_arg and os.path.isfile(hosts_file_arg):
        from freq.core.config import load_hosts, load_hosts_toml

        try:
            if hosts_file_arg.endswith(".toml"):
                scoped_hosts = load_hosts_toml(hosts_file_arg)
            else:
                scoped_hosts = load_hosts(hosts_file_arg)
            fmt.step_ok(f"Explicit hosts file loaded: {len(scoped_hosts)} host(s)")
        except Exception as e:
            fmt.step_warn(f"Could not load --hosts-file for discovery scope: {e}")
            scoped_hosts = []

    # Track all discovered hosts: ip -> {label, htype, groups, vmid, source, all_ips}
    discovered = {}
    existing_hosts = list(cfg.hosts)
    seen_existing = {h.ip for h in existing_hosts}
    for h in scoped_hosts:
        if h.ip not in seen_existing:
            existing_hosts.append(h)
            seen_existing.add(h.ip)
    existing_ips = {h.ip for h in existing_hosts}
    scoped_infra_types = {h.htype for h in scoped_hosts if h.htype in {"pfsense", "truenas", "switch", "idrac"}}

    # ── Step 1: PVE API Discovery (primary mechanism) ──────────────
    fmt.line(f"  {fmt.C.BOLD}Step 1: PVE Cluster Discovery{fmt.C.RESET}")
    fmt.blank()

    pve_vms = []
    if cfg.pve_nodes:
        # Try API first (if token was created in Phase 6), fall back to SSH
        api_ok = False
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            try:
                from freq.modules.pve import _pve_api_call
                result, ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/cluster/resources?type=vm")
                if ok and isinstance(result, list):
                    pve_vms = result
                    api_ok = True
                    fmt.step_ok(f"PVE API: {len(pve_vms)} VMs/CTs found")
            except Exception:
                pass

        if not api_ok:
            # SSH fallback
            fmt.step_start("Querying PVE cluster via SSH...")
            for node_ip in cfg.pve_nodes:
                rc, out, _ = _run(
                    ["ssh", "-n", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                     "-i", key_path, f"{svc_name}@{node_ip}",
                     "sudo pvesh get /cluster/resources --type vm --output-format json 2>/dev/null"],
                    timeout=DEFAULT_CMD_TIMEOUT,
                )
                if rc == 0 and out.strip():
                    try:
                        pve_vms = _json.loads(out)
                        fmt.step_ok(f"PVE SSH: {len(pve_vms)} VMs/CTs found")
                        break  # Cluster API returns all VMs from any healthy node
                    except _json.JSONDecodeError:
                        pass

    if not pve_vms:
        fmt.step_warn("No VMs returned from PVE — skipping PVE-based discovery")
    else:
        # Get IPs for running VMs via QEMU guest agent
        running_vms = [v for v in pve_vms if v.get("status") == "running" and v.get("type") == "qemu"]
        fmt.step_start(f"Resolving IPs for {len(running_vms)} running VMs via guest agent...")

        # Derive management VLAN prefix from PVE node IPs
        mgmt_prefixes = set()
        for nip in cfg.pve_nodes:
            parts = nip.rsplit(".", 1)
            if len(parts) == 2:
                mgmt_prefixes.add(parts[0] + ".")

        resolved = 0
        unresolved = 0
        for v in running_vms:
            vmid = v.get("vmid", 0)
            name = v.get("name", "")
            node = v.get("node", "")

            if not name or vmid < 100:
                continue

            # Find PVE node IP for this VM
            node_ip = None
            for i, pn in enumerate(getattr(cfg, "pve_node_names", []) or []):
                if pn == node and i < len(cfg.pve_nodes):
                    node_ip = cfg.pve_nodes[i]
                    break
            if not node_ip:
                node_ip = cfg.pve_nodes[0] if cfg.pve_nodes else None
            if not node_ip:
                continue

            # Get IPs via guest agent — try API first, then SSH
            all_ips = []
            agent_data = None

            if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
                try:
                    from freq.modules.pve import _pve_api_call
                    result, ok = _pve_api_call(
                        cfg, node_ip,
                        f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces",
                    )
                    if ok:
                        agent_data = result
                except Exception:
                    pass

            if agent_data is None:
                # SSH fallback
                rc, out, _ = _run(
                    ["ssh", "-n", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
                     "-i", key_path, f"{svc_name}@{node_ip}",
                     f"sudo qm agent {vmid} network-get-interfaces 2>/dev/null"],
                    timeout=10,
                )
                if rc == 0 and out.strip():
                    try:
                        data = _json.loads(out)
                        agent_data = data.get("result", data) if isinstance(data, dict) else data
                    except (_json.JSONDecodeError, ValueError):
                        pass

            if agent_data is None:
                unresolved += 1
                continue

            # Handle both list and dict formats from guest agent
            ifaces = agent_data if isinstance(agent_data, list) else agent_data.get("result", agent_data) if isinstance(agent_data, dict) else []
            if isinstance(ifaces, dict):
                ifaces = ifaces.get("result", []) if "result" in ifaces else []

            for iface in ifaces if isinstance(ifaces, list) else []:
                for addr in iface.get("ip-addresses", []):
                    if addr.get("ip-address-type") == "ipv4":
                        ip = addr.get("ip-address", "")
                        if ip and not ip.startswith("127.") and not _is_docker_bridge_ip(ip):
                            all_ips.append(ip)

            if not all_ips:
                unresolved += 1
                continue

            # Smart IP selection: prefer management VLAN
            chosen_ip = None
            for ip in all_ips:
                if ip in existing_ips or ip in discovered:
                    chosen_ip = ip
                    break
            if not chosen_ip:
                mgmt_ips = [ip for ip in all_ips if any(ip.startswith(p) for p in mgmt_prefixes)]
                chosen_ip = mgmt_ips[0] if mgmt_ips else all_ips[0]

            # Auto-classify type
            htype = _classify_host_by_name(name)

            # An explicit hosts file is the source of truth for infrastructure.
            if scoped_hosts and htype in scoped_infra_types:
                continue

            if chosen_ip not in existing_ips and chosen_ip not in discovered:
                try:
                    from freq.core.validate import sanitize_label
                    safe_label = sanitize_label(name)
                except ImportError:
                    safe_label = name.lower().replace(" ", "-")
                discovered[chosen_ip] = {
                    "label": safe_label,
                    "htype": htype,
                    "groups": "",
                    "vmid": vmid,
                    "source": "pve-api",
                    "all_ips": all_ips,
                }
                resolved += 1

        # Also add PVE nodes themselves to discovered for fleet-boundaries
        for i, nip in enumerate(cfg.pve_nodes):
            pn = cfg.pve_node_names[i] if i < len(getattr(cfg, "pve_node_names", []) or []) else f"pve{i+1}"
            if nip not in existing_ips and nip not in discovered:
                discovered[nip] = {
                    "label": pn,
                    "htype": "pve",
                    "groups": "cluster",
                    "vmid": 0,
                    "source": "pve-node",
                    "all_ips": [nip],
                }

        if resolved or unresolved:
            fmt.step_ok(f"Guest agent: {resolved} VMs resolved, {unresolved} unresolved")

    # ── Step 2: Multi-VLAN Ping Sweep (supplement) ─────────────────
    vlans = getattr(cfg, "vlans", []) or []
    if vlans:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Step 2: Multi-VLAN Discovery{fmt.C.RESET}")
        fmt.blank()

        already_known = existing_ips | set(discovered.keys())
        known_labels = {d["label"].lower() for d in discovered.values()}
        known_labels |= {h.label.lower() for h in existing_hosts}

        for vlan in vlans:
            prefix = getattr(vlan, "prefix", "") or ""
            vlan_name = getattr(vlan, "name", "") or f"VLAN{getattr(vlan, 'id', '?')}"
            if not prefix:
                continue

            fmt.step_start(f"Scanning {vlan_name} ({prefix}.0/24)...")
            try:
                from freq.modules.discover import scan_and_identify
                alive, hosts_info = scan_and_identify(prefix, key_path, cfg=cfg)

                new_on_vlan = 0
                for h in hosts_info:
                    if not h.get("reachable") or h["ip"] in already_known:
                        continue
                    hostname = h.get("hostname", "") or f"host-{h['ip'].split('.')[-1]}"
                    # Skip if same hostname already registered (different VLAN for same host)
                    if hostname.lower() in known_labels:
                        continue
                    discovered[h["ip"]] = {
                        "label": hostname,
                        "htype": h.get("type", "linux"),
                        "groups": vlan_name.lower().replace("/", "-"),
                        "vmid": 0,
                        "source": f"vlan-scan",
                        "all_ips": [h["ip"]],
                    }
                    already_known.add(h["ip"])
                    known_labels.add(hostname.lower())
                    new_on_vlan += 1

                if new_on_vlan:
                    fmt.step_ok(f"{vlan_name}: {new_on_vlan} new host(s)")
                else:
                    fmt.step_ok(f"{vlan_name}: {len(alive)} alive, 0 new")
            except Exception as e:
                fmt.step_warn(f"{vlan_name} scan failed: {e}")
    else:
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}No VLANs configured — skipping multi-VLAN scan.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run 'freq host discover' later to scan subnets manually.{fmt.C.RESET}")

    # ── Step 3: Infrastructure Auto-Detection ──────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Step 3: Infrastructure Detection{fmt.C.RESET}")
    fmt.blank()

    infra_pfsense = ""
    infra_truenas = ""
    infra_switch = ""

    # Gateway = firewall
    gw = getattr(cfg, "vm_gateway", "") or ""
    if gw and gw not in existing_ips:
        if gw in discovered:
            # Already discovered — check/update type
            if discovered[gw]["htype"] == "linux":
                discovered[gw]["htype"] = "pfsense"
                discovered[gw]["label"] = "firewall"
            infra_pfsense = gw
            fmt.step_ok(f"Gateway {gw} → firewall ({discovered[gw]['htype']})")
        else:
            # Probe gateway
            rc, _, _ = _run(["ping", "-c", "1", "-W", "1", gw], timeout=PING_TIMEOUT)
            if rc == 0:
                # Try SSH fingerprint
                gw_type = "pfsense"
                try:
                    rc2, out2, _ = _run(
                        ["ssh", "-n", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
                         "-o", "StrictHostKeyChecking=accept-new",
                         "-i", key_path, f"{svc_name}@{gw}", "uname -s"],
                        timeout=QUICK_CHECK_TIMEOUT,
                    )
                    if rc2 == 0:
                        if "Linux" in out2:
                            gw_type = "opnsense"
                except Exception:
                    pass

                discovered[gw] = {
                    "label": "firewall",
                    "htype": gw_type,
                    "groups": "infrastructure",
                    "vmid": 0,
                    "source": "gateway-probe",
                    "all_ips": [gw],
                }
                infra_pfsense = gw
                fmt.step_ok(f"Gateway {gw} → {gw_type}")
            else:
                fmt.step_warn(f"Gateway {gw} not responding to ping")
    elif gw and gw in existing_ips:
        infra_pfsense = gw
        fmt.step_ok(f"Gateway {gw} already registered")

    # Detect TrueNAS, switch, iDRAC from discovered hosts
    for ip, d in discovered.items():
        if d["htype"] == "truenas" and not infra_truenas:
            infra_truenas = ip
            fmt.step_ok(f"TrueNAS detected: {d['label']} ({ip})")
        elif d["htype"] == "switch" and not infra_switch:
            infra_switch = ip
            fmt.step_ok(f"Switch detected: {d['label']} ({ip})")

    # Also check existing hosts for infrastructure
    for h in existing_hosts:
        if h.htype == "truenas" and not infra_truenas:
            infra_truenas = h.ip
        elif h.htype == "switch" and not infra_switch:
            infra_switch = h.ip
        elif h.htype == "pfsense" and not infra_pfsense:
            infra_pfsense = h.ip

    # ── Probe for infrastructure devices on well-known IPs ────────
    # iDRAC/BMC, switch, TrueNAS are often missed by VLAN scan because
    # they use legacy SSH or non-standard protocols. Probe explicitly.
    infra_idrac_ips = []
    all_known_ips = set(discovered.keys()) | existing_ips

    # Probe known infrastructure subnets for iDRAC, switch, TrueNAS
    # Use the management subnet from PVE nodes to derive likely IPs
    mgmt_prefix = ""
    if cfg.pve_nodes:
        parts = cfg.pve_nodes[0].rsplit(".", 1)
        if len(parts) == 2:
            mgmt_prefix = parts[0]

    if mgmt_prefix:
        # iDRAC devices — common range .10-.15
        for last_octet in range(10, 16):
            ip = f"{mgmt_prefix}.{last_octet}"
            if ip in all_known_ips:
                continue
            rc, _, _ = _run(["ping", "-c", "1", "-W", "1", ip], timeout=PING_TIMEOUT)
            if rc == 0:
                # Try SSH banner check for iDRAC
                rc2, out2, _ = _run(
                    ["ssh", "-n", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes",
                     "-o", "StrictHostKeyChecking=accept-new",
                     "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                     "-o", "HostKeyAlgorithms=+ssh-rsa",
                     f"root@{ip}", "racadm getversion"],
                    timeout=QUICK_CHECK_TIMEOUT,
                )
                if rc2 == 0 and ("racadm" in out2.lower() or "idrac" in out2.lower() or "version" in out2.lower()):
                    label = f"idrac-{ip.split('.')[-1]}"
                    discovered[ip] = {
                        "label": label, "htype": "idrac",
                        "groups": "infrastructure", "vmid": 0,
                        "source": "infra-probe", "all_ips": [ip],
                    }
                    infra_idrac_ips.append(ip)
                    fmt.step_ok(f"iDRAC detected: {label} ({ip})")
                else:
                    # Still reachable but not confirmed iDRAC — add as possible BMC
                    label = f"bmc-{ip.split('.')[-1]}"
                    discovered[ip] = {
                        "label": label, "htype": "idrac",
                        "groups": "infrastructure", "vmid": 0,
                        "source": "infra-probe-ping", "all_ips": [ip],
                    }
                    infra_idrac_ips.append(ip)
                    fmt.step_ok(f"BMC reachable: {label} ({ip})")

        # Switch — common at .5
        if not infra_switch:
            for last_octet in [5, 6]:
                ip = f"{mgmt_prefix}.{last_octet}"
                if ip in all_known_ips:
                    continue
                rc, _, _ = _run(["ping", "-c", "1", "-W", "1", ip], timeout=PING_TIMEOUT)
                if rc == 0:
                    discovered[ip] = {
                        "label": "switch", "htype": "switch",
                        "groups": "infrastructure", "vmid": 0,
                        "source": "infra-probe", "all_ips": [ip],
                    }
                    infra_switch = ip
                    fmt.step_ok(f"Switch detected: {ip}")
                    break

        # TrueNAS — common at .25
        if not infra_truenas:
            for last_octet in [25]:
                ip = f"{mgmt_prefix}.{last_octet}"
                if ip in all_known_ips:
                    continue
                rc, _, _ = _run(["ping", "-c", "1", "-W", "1", ip], timeout=PING_TIMEOUT)
                if rc == 0:
                    discovered[ip] = {
                        "label": "truenas", "htype": "truenas",
                        "groups": "infrastructure", "vmid": 0,
                        "source": "infra-probe", "all_ips": [ip],
                    }
                    infra_truenas = ip
                    fmt.step_ok(f"TrueNAS detected: {ip}")

    if not infra_truenas and not infra_switch and not infra_idrac_ips:
        fmt.line(f"  {fmt.C.DIM}No additional infrastructure devices auto-detected.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Add manually later with 'freq host add'.{fmt.C.RESET}")

    # ── Step 4: Register discovered hosts ──────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Step 4: Fleet Registration{fmt.C.RESET}")
    fmt.blank()

    if not discovered:
        fmt.line(f"  {fmt.C.DIM}No new hosts discovered.{fmt.C.RESET}")
        if not cfg.hosts:
            fmt.line(f"  {fmt.C.DIM}Add hosts manually with 'freq host add' or 'freq host discover'.{fmt.C.RESET}")
    else:
        headless = getattr(args, "headless", False) if args else False

        # Display discovery table
        fmt.table_header(
            ("IP", 17), ("LABEL", 20), ("TYPE", 10), ("SOURCE", 12),
        )
        for ip, d in sorted(discovered.items(), key=lambda x: x[0]):
            type_color = {
                "pve": fmt.C.PURPLE, "linux": fmt.C.GREEN, "docker": fmt.C.CYAN,
                "truenas": fmt.C.BLUE, "pfsense": fmt.C.YELLOW, "idrac": fmt.C.RED,
                "switch": fmt.C.RED, "opnsense": fmt.C.YELLOW,
            }.get(d["htype"], fmt.C.GRAY)
            fmt.table_row(
                (ip, 17), (d["label"][:20], 20),
                (f"{type_color}{d['htype']}{fmt.C.RESET}", 10),
                (d["source"][:12], 12),
            )

        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}{len(discovered)} new host(s) discovered.{fmt.C.RESET}")
        fmt.blank()

        if headless:
            if scoped_hosts:
                fmt.step_ok(f"Explicit hosts file provided — skipped auto-registration of {len(discovered)} discovered host(s)")
            else:
                # Auto-register all in headless mode
                # Use save (overwrite) instead of append to prevent duplicates
                # from seeded template files or repeated runs
                from freq.core.config import save_hosts_toml
                for ip, d in discovered.items():
                    host = Host(ip=ip, label=d["label"], htype=d["htype"], groups=d.get("groups", ""))
                    cfg.hosts.append(host)
                save_hosts_toml(cfg.hosts_file, cfg.hosts)
                fmt.step_ok(f"Auto-registered {len(discovered)} host(s)")
        else:
            # Interactive: confirm registration
            if _confirm(f"Register all {len(discovered)} discovered hosts?", default=True):
                from freq.core.config import save_hosts_toml
                for ip, d in discovered.items():
                    host = Host(ip=ip, label=d["label"], htype=d["htype"], groups=d.get("groups", ""))
                    cfg.hosts.append(host)
                save_hosts_toml(cfg.hosts_file, cfg.hosts)
                fmt.step_ok(f"Registered {len(discovered)} host(s)")
            else:
                # One-by-one confirmation
                from freq.core.config import save_hosts_toml
                registered = 0
                for ip, d in discovered.items():
                    if _confirm(f"  Register {d['label']} ({ip}) [{d['htype']}]?", default=True):
                        label = _input(f"    Label", d["label"])
                        htype = _input(f"    Type", d["htype"])
                        host = Host(ip=ip, label=label, htype=htype, groups=d.get("groups", ""))
                        cfg.hosts.append(host)
                        registered += 1
                save_hosts_toml(cfg.hosts_file, cfg.hosts)
                fmt.step_ok(f"Registered {registered}/{len(discovered)} host(s)")

        # Offer to add non-discoverable devices manually
        if not headless:
            fmt.blank()
            fmt.line(
                f"  {fmt.C.DIM}Network scan can't find all devices (iDRAC, managed switches).{fmt.C.RESET}"
            )
            if _confirm("Add additional devices manually?"):
                fmt.blank()
                fmt.line(f"  {fmt.C.DIM}Enter hosts one at a time. Press Enter with empty IP to stop.{fmt.C.RESET}")
                fmt.blank()
                while True:
                    if not _register_host_interactive(cfg):
                        break
                    fmt.blank()

    # ── Step 5: Write fleet-boundaries.toml ───��────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Step 5: Fleet Boundaries{fmt.C.RESET}")
    fmt.blank()

    try:
        from freq.modules.hosts import _auto_populate_fleet_boundaries
        _auto_populate_fleet_boundaries(cfg, discovered)
        fmt.step_ok("fleet-boundaries.toml updated with discovered devices")
    except Exception as e:
        fmt.step_warn(f"Could not update fleet-boundaries: {e}")

    # ── Step 6: Update freq.toml [infrastructure] ──────────────────
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    infra_updated = False
    try:
        with open(toml_path) as f:
            content = f.read()

        if infra_pfsense:
            content = _update_toml_value(content, "pfsense_ip", infra_pfsense)
            cfg.pfsense_ip = infra_pfsense
            infra_updated = True
        if infra_truenas:
            content = _update_toml_value(content, "truenas_ip", infra_truenas)
            cfg.truenas_ip = infra_truenas
            infra_updated = True
        if infra_switch:
            content = _update_toml_value(content, "switch_ip", infra_switch)
            cfg.switch_ip = infra_switch
            infra_updated = True

        if infra_updated:
            with open(toml_path, "w") as f:
                f.write(content)
            fmt.step_ok("freq.toml [infrastructure] updated")
        else:
            fmt.line(f"  {fmt.C.DIM}No infrastructure IPs to update in freq.toml.{fmt.C.RESET}")
    except OSError as e:
        fmt.step_warn(f"Could not update freq.toml infrastructure: {e}")

    fmt.blank()
    total_fleet = len(cfg.hosts) if cfg.hosts else len(scoped_hosts)
    fmt.line(f"  {fmt.C.GREEN}Fleet: {total_fleet} host(s) registered.{fmt.C.RESET}")
    logger.info("init_phase_complete: Phase 7 - fleet_discover", phase=7, hosts=total_fleet)
    audit.record("config_write", "hosts.toml", "success", hosts=total_fleet)


# ═══════════════════════════════════════════════════════════════════
# PHASE 8: Fleet Deployment
# ════════════════════════════════════════════════════════════��══════


def _phase_fleet_deploy(cfg, ctx, args=None):
    """Deploy service account + key to fleet hosts (all platform types)."""
    logger.info("init_phase_start: Phase 8 - fleet_deploy", phase=8)
    # Load per-device credentials (--device-credentials TOML)
    device_creds_file = getattr(args, "device_credentials", None) if args else None
    device_creds = _load_device_credentials(device_creds_file)
    if device_creds:
        fmt.step_ok(f"Device credentials loaded: {', '.join(sorted(device_creds.keys()))}")

    # Import hosts from file if --hosts-file provided (headless/automation)
    hosts_file_arg = getattr(args, "hosts_file", None) if args else None
    if hosts_file_arg and os.path.isfile(hosts_file_arg) and not cfg.hosts:
        fmt.step_start(f"Importing fleet hosts from {hosts_file_arg}")
        shutil.copy2(hosts_file_arg, cfg.hosts_file)
        from freq.core.config import load_hosts, load_hosts_toml

        try:
            if hosts_file_arg.endswith(".toml"):
                cfg.hosts = load_hosts_toml(cfg.hosts_file)
            else:
                cfg.hosts = load_hosts(cfg.hosts_file)
            fmt.step_ok(f"Imported {len(cfg.hosts)} host(s) from {hosts_file_arg}")
        except Exception as e:
            fmt.step_fail(f"Failed to reload hosts: {e}")

    if not cfg.hosts:
        fmt.line(f"  {fmt.C.DIM}No hosts registered — nothing to deploy.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Add hosts with 'freq host add' or re-run 'freq init'.{fmt.C.RESET}")
        return

    # Group hosts by auth category (using deployer registry)
    linux_hosts = [h for h in cfg.hosts if h.category == "server"]
    pfsense_hosts = [h for h in cfg.hosts if h.category == "firewall"]
    device_hosts = [h for h in cfg.hosts if h.category in ("bmc", "switch")]
    nas_hosts = [h for h in cfg.hosts if h.category == "nas"]
    # NAS hosts use server deployer (same SSH+useradd flow)
    linux_hosts.extend(nas_hosts)

    total = len(linux_hosts) + len(pfsense_hosts) + len(device_hosts)
    fmt.line(
        f"  {fmt.C.DIM}Fleet: {len(linux_hosts)} server, "
        f"{len(pfsense_hosts)} firewall, "
        f"{len(device_hosts)} device(s) — {total} total{fmt.C.RESET}"
    )
    fmt.blank()

    ok = fail = 0
    deployed_ips = set()  # Track IPs we deployed to — Phase 12 uses this
    legacy_passwords = set()

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
                before = audit.snapshot_host(h.ip, ctx["svc_name"], h.htype, cfg)
                if _deploy_to_host_dispatch(h.ip, h.htype, ctx, linux_pass, linux_key, linux_user):
                    ok += 1
                    deployed_ips.add(h.ip)
                    after = audit.snapshot_host(h.ip, ctx["svc_name"], h.htype, cfg)
                    audit.record_change(h.ip, "deploy_user", before, after)
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
                        before = audit.snapshot_host(h.ip, ctx["svc_name"], h.htype, cfg)
                        if _deploy_to_host_dispatch(h.ip, h.htype, ctx, linux_pass, linux_key, linux_user):
                            ok += 1
                            after = audit.snapshot_host(h.ip, ctx["svc_name"], h.htype, cfg)
                            audit.record_change(h.ip, "deploy_user", before, after)
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
                before = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                    ok += 1
                    deployed_ips.add(h.ip)
                    after = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                    audit.record_change(h.ip, "deploy_user", before, after)
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
                before = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                    ok += 1
                    deployed_ips.add(h.ip)
                    after = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                    audit.record_change(h.ip, "deploy_user", before, after)
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
                        before = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                        if _deploy_to_host_dispatch(h.ip, "pfsense", ctx, pf_pass, pf_key, pf_user):
                            ok += 1
                            after = audit.snapshot_host(h.ip, ctx["svc_name"], "pfsense", cfg)
                            audit.record_change(h.ip, "deploy_user", before, after)
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
                    deployed_ips.add(h.ip)
                    legacy_passwords.add(creds["password"])
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
                        deployed_ips.add(h.ip)
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
                        dev_pass = getpass.getpass(
                            f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for device admin ({dev_user}): "
                        )
                        for h in dev_without_creds:
                            fmt.blank()
                            fmt.line(f"  {fmt.C.BOLD}{h.label}{fmt.C.RESET} ({h.ip}) [{h.htype}]")
                            if _deploy_to_host_dispatch(h.ip, h.htype, ctx, dev_pass, "", dev_user):
                                ok += 1
                                deployed_ips.add(h.ip)
                                legacy_passwords.add(dev_pass)
                            else:
                                fail += 1
                else:
                    fmt.step_warn("Skipping device hosts")

    # Persist device (iDRAC/switch) password for ongoing SSH access
    if device_hosts and ok > 0 and legacy_passwords:
        if len(legacy_passwords) == 1:
            _persist_legacy_password_file(cfg, ctx["svc_name"], next(iter(legacy_passwords)))
        else:
            fmt.step_warn("Multiple distinct iDRAC/switch passwords used — legacy password fallback not persisted")

    # Store deployed IPs for Phase 12 — deployed hosts MUST pass verification
    ctx["deployed_ips"] = deployed_ips
    ctx["fleet_deploy_failures"] = fail

    fmt.blank()
    fmt.line(f"  Fleet deployment: {fmt.C.GREEN}{ok} OK{fmt.C.RESET}, {fmt.C.RED}{fail} failed{fmt.C.RESET}")
    logger.info("init_phase_complete: Phase 8 - fleet_deploy", phase=8, ok=ok, fail=fail)


# ═══════════════════════════════════════════════════════════════════
# PHASE 9: Fleet Configuration
# ═══════════════════════════════════════════════════════════════════


def _phase_fleet_configure(cfg, ctx):
    """Post-deployment fleet configuration.

    9a: Verify and tag Docker hosts (add freq-admin to docker group).
    9b: Deploy metrics agent to all Linux-family hosts.
    9c: Auto-categorize VMs into fleet-boundary tiers.
    """
    logger.info("init_phase_start: Phase 9 - fleet_configure", phase=9)
    import json as _json

    key_path = ctx.get("key_path", "") or cfg.ssh_key_path
    svc_name = ctx.get("svc_name", cfg.ssh_service_account)

    if not cfg.hosts or not key_path or not os.path.isfile(key_path):
        fmt.line(f"  {fmt.C.DIM}No hosts or keys available — skipping fleet configuration.{fmt.C.RESET}")
        return

    ssh_base_opts = [
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-i", key_path,
    ]

    # ── 9a: Docker — Verify, Tag, Discover Containers ───────────
    docker_hosts = [h for h in cfg.hosts if h.htype == "docker"]
    verified_docker_hosts = []  # hosts where docker is confirmed working

    if docker_hosts:
        fmt.line(f"  {fmt.C.BOLD}Docker Host Setup ({len(docker_hosts)} hosts){fmt.C.RESET}")
        fmt.blank()

        for h in docker_hosts:
            ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [f"{svc_name}@{h.ip}"]
            # Check docker is installed
            rc, out, _ = _run(ssh_cmd + ["docker --version 2>/dev/null"], timeout=QUICK_CHECK_TIMEOUT)
            if rc == 0 and "Docker" in out:
                # Add service account to docker group
                _run(
                    ssh_cmd + [f"sudo usermod -aG docker {svc_name} 2>/dev/null"],
                    timeout=QUICK_CHECK_TIMEOUT,
                )
                verified_docker_hosts.append(h)
                fmt.step_ok(f"{h.label}: Docker verified, {svc_name} added to docker group")
            else:
                fmt.step_warn(f"{h.label}: tagged as docker but docker not installed")

        # Discover containers on each verified docker host
        if verified_docker_hosts:
            fmt.blank()
            fmt.line(f"  {fmt.C.BOLD}Docker Container Discovery{fmt.C.RESET}")
            fmt.blank()

            all_containers = {}  # host_label -> list of container dicts
            total_containers = 0
            primary_docker_ip = ""
            primary_docker_count = 0

            for h in verified_docker_hosts:
                ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [f"{svc_name}@{h.ip}"]
                # Get running containers as JSON
                rc, out, _ = _run(
                    ssh_cmd + [
                        "sudo docker ps --format '{{json .}}' 2>/dev/null"
                    ],
                    timeout=DEFAULT_CMD_TIMEOUT,
                )
                if rc != 0 or not out.strip():
                    # Try without sudo (service account may already be in docker group from a prior init)
                    rc, out, _ = _run(
                        ssh_cmd + [
                            "docker ps --format '{{json .}}' 2>/dev/null"
                        ],
                        timeout=DEFAULT_CMD_TIMEOUT,
                    )

                containers = []
                if rc == 0 and out.strip():
                    for line in out.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            c = _json.loads(line)
                            containers.append({
                                "name": c.get("Names", "unknown"),
                                "image": c.get("Image", ""),
                                "status": c.get("Status", ""),
                                "ports": c.get("Ports", ""),
                            })
                        except (_json.JSONDecodeError, ValueError):
                            pass

                if containers:
                    all_containers[h.label] = {"ip": h.ip, "containers": containers}
                    total_containers += len(containers)
                    fmt.step_ok(f"{h.label}: {len(containers)} container(s) running")

                    # Track which docker host has the most containers → primary
                    if len(containers) > primary_docker_count:
                        primary_docker_count = len(containers)
                        primary_docker_ip = h.ip
                else:
                    fmt.line(f"  {fmt.C.DIM}{h.label}: no running containers{fmt.C.RESET}")

                # Also discover compose paths
                rc2, out2, _ = _run(
                    ssh_cmd + [
                        "sudo find /opt /home -maxdepth 3 -name 'docker-compose.yml' -o -name 'compose.yml' 2>/dev/null | head -20"
                    ],
                    timeout=DEFAULT_CMD_TIMEOUT,
                )
                if rc2 == 0 and out2.strip():
                    compose_paths = [p.strip() for p in out2.strip().split("\n") if p.strip()]
                    if compose_paths and h.label in all_containers:
                        # Find common base path
                        dirs = [os.path.dirname(p) for p in compose_paths]
                        if dirs:
                            # Get shortest common prefix
                            common = os.path.commonpath(dirs) if len(dirs) > 1 else os.path.dirname(dirs[0])
                            all_containers[h.label]["compose_path"] = common

            # Write containers.toml
            if all_containers:
                containers_path = os.path.join(cfg.conf_dir, "containers.toml")
                try:
                    lines = [
                        "# FREQ Container Registry",
                        "# Auto-discovered by freq init",
                        "",
                    ]
                    for host_label, data in sorted(all_containers.items()):
                        # Find vmid for this host
                        vmid = 0
                        for h in cfg.hosts:
                            if h.label == host_label:
                                # Try to get vmid from PVE
                                break

                        lines.append(f"[host.{host_label}]")
                        lines.append(f'ip = "{data["ip"]}"')
                        lines.append(f'label = "{host_label}"')
                        if data.get("compose_path"):
                            lines.append(f'compose_path = "{data["compose_path"]}"')
                        lines.append("")

                        for c in data["containers"]:
                            safe_name = c["name"].replace("-", "_").replace(".", "_").lower()
                            lines.append(f"[host.{host_label}.containers.{safe_name}]")
                            lines.append(f'name = "{c["name"]}"')
                            lines.append(f'image = "{c["image"]}"')
                            lines.append(f'status = "{c["status"]}"')
                            lines.append("")

                    with open(containers_path, "w") as f:
                        f.write("\n".join(lines))
                    fmt.step_ok(f"containers.toml: {total_containers} containers across {len(all_containers)} hosts")
                except OSError as e:
                    fmt.step_warn(f"Could not write containers.toml: {e}")

            # Set docker_dev_ip in freq.toml (primary docker host)
            if primary_docker_ip:
                toml_path = os.path.join(cfg.conf_dir, "freq.toml")
                try:
                    with open(toml_path) as f:
                        content = f.read()
                    content = _update_toml_value(content, "docker_dev_ip", primary_docker_ip)
                    with open(toml_path, "w") as f:
                        f.write(content)
                    cfg.docker_dev_ip = primary_docker_ip
                    fmt.step_ok(f"docker_dev_ip set to {primary_docker_ip}")
                except OSError:
                    pass

            fmt.blank()
            fmt.line(f"  {fmt.C.GREEN}Docker: {total_containers} containers on {len(verified_docker_hosts)} hosts{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.DIM}No Docker hosts to configure.{fmt.C.RESET}")

    # ── 9b: Metrics Agent Deployment ──────────────────────────────
    fmt.blank()
    agent_hosts = [h for h in cfg.hosts if h.htype in ("linux", "pve", "docker", "truenas")]
    if agent_hosts:
        fmt.line(f"  {fmt.C.BOLD}Metrics Agent Deployment ({len(agent_hosts)} hosts){fmt.C.RESET}")
        fmt.blank()

        # Find the agent_collector.py source file — check relative to this module, then install_dir
        agent_src = None
        for candidate in [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_collector.py"),
            os.path.join(cfg.install_dir, "freq", "agent_collector.py"),
        ]:
            if os.path.isfile(candidate):
                agent_src = candidate
                break

        if not agent_src:
            fmt.step_warn("agent_collector.py not found — skipping agent deployment")
        else:
            agent_port = getattr(cfg, "agent_port", 9990) or 9990
            agent_ok = agent_fail = 0

            for h in agent_hosts:
                ssh_target = f"{svc_name}@{h.ip}"
                ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [ssh_target]

                # Test connectivity first
                rc, _, _ = _run(ssh_cmd + ["echo ok"], timeout=QUICK_CHECK_TIMEOUT)
                if rc != 0:
                    agent_fail += 1
                    continue

                # Upload agent via SSH + cat
                try:
                    with open(agent_src) as f:
                        agent_code = f.read()
                except OSError:
                    fmt.step_warn(f"Cannot read {agent_src}")
                    break

                # Create dir + upload
                setup_script = (
                    f"sudo mkdir -p {AGENT_REMOTE_DIR} && "
                    f"sudo tee {AGENT_REMOTE_PATH} > /dev/null && "
                    f"sudo chmod +x {AGENT_REMOTE_PATH}"
                )
                try:
                    # No -n flag here — we pipe agent_code via stdin to tee
                    r = subprocess.run(
                        ["ssh"] + ssh_base_opts + [ssh_target, setup_script],
                        input=agent_code, capture_output=True, text=True, timeout=DEFAULT_CMD_TIMEOUT,
                    )
                    if r.returncode != 0:
                        agent_fail += 1
                        continue
                except Exception:
                    agent_fail += 1
                    continue

                # Create systemd service
                unit = (
                    "[Unit]\n"
                    "Description=FREQ Metrics Agent\n"
                    "After=network.target\n"
                    "\n"
                    "[Service]\n"
                    f"Environment=FREQ_AGENT_PORT={agent_port}\n"
                    f"ExecStart=/usr/bin/env python3 {AGENT_REMOTE_PATH}\n"
                    "Restart=always\n"
                    "RestartSec=10\n"
                    "\n"
                    "[Install]\n"
                    "WantedBy=multi-user.target\n"
                )
                unit_cmd = (
                    f"echo '{unit}' | sudo tee /etc/systemd/system/freq-agent.service > /dev/null && "
                    "sudo systemctl daemon-reload && "
                    "sudo systemctl enable freq-agent --now 2>/dev/null"
                )
                rc, _, _ = _run(ssh_cmd + [unit_cmd], timeout=DEFAULT_CMD_TIMEOUT)
                if rc == 0:
                    agent_ok += 1
                else:
                    agent_fail += 1

            fmt.step_ok(f"Agent deployed: {agent_ok} OK, {agent_fail} failed")
    else:
        fmt.line(f"  {fmt.C.DIM}No agent-capable hosts found.{fmt.C.RESET}")

    # ── 9c: VM Categorization ─────────────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}VM Categorization{fmt.C.RESET}")
    fmt.blank()

    categories = _categorize_vms(cfg)
    if categories:
        fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")
        try:
            # Strip old [categories.*] sections before writing to prevent
            # duplicate TOML table headers on re-run (append is not idempotent)
            try:
                with open(fb_path) as _fb:
                    _fb_lines = _fb.readlines()
            except FileNotFoundError:
                _fb_lines = []
            _fb_clean = []
            _fb_skip = False
            for _ln in _fb_lines:
                _s = _ln.strip()
                if _s.startswith("[categories."):
                    _fb_skip = True
                    continue
                if _fb_skip:
                    if _s.startswith("[") and not _s.startswith("[categories."):
                        _fb_skip = False
                        _fb_clean.append(_ln)
                    else:
                        continue
                else:
                    if _s == "# Auto-categorized VM groups":
                        continue
                    _fb_clean.append(_ln)
            while _fb_clean and _fb_clean[-1].strip() == "":
                _fb_clean.pop()
            with open(fb_path, "w") as f:
                f.writelines(_fb_clean)
                f.write("\n\n# Auto-categorized VM groups\n")
                for cat_name, cat_data in sorted(categories.items()):
                    vmids = cat_data["vmids"]
                    if not vmids:
                        continue
                    f.write(f"\n[categories.{cat_name}]\n")
                    f.write(f'description = "{cat_data["description"]}"\n')
                    f.write(f'tier = "{cat_data["tier"]}"\n')
                    if cat_data.get("range_start") is not None:
                        f.write(f"range_start = {cat_data['range_start']}\n")
                        f.write(f"range_end = {cat_data['range_end']}\n")
                    else:
                        f.write(f"vmids = {vmids}\n")
            fmt.step_ok(f"VM categories written: {', '.join(categories.keys())}")
        except OSError as e:
            fmt.step_warn(f"Could not update fleet-boundaries: {e}")
    else:
        fmt.line(f"  {fmt.C.DIM}No VMs to categorize (PVE API unavailable or no VMs found).{fmt.C.RESET}")

    # ── 9d: QEMU Guest Agent Install ─────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}QEMU Guest Agent Housekeeping{fmt.C.RESET}")
    fmt.blank()

    # Find Linux hosts that are VMs (not PVE nodes themselves, not physical devices)
    vm_hosts = [h for h in cfg.hosts if h.htype in ("linux", "docker") and h.ip not in set(cfg.pve_nodes or [])]
    if vm_hosts:
        installed_count = 0
        already_count = 0
        for h in vm_hosts:
            ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [f"{svc_name}@{h.ip}"]
            # Check if guest agent is already running
            rc, _, _ = _run(ssh_cmd + ["systemctl is-active qemu-guest-agent 2>/dev/null"], timeout=QUICK_CHECK_TIMEOUT)
            if rc == 0:
                already_count += 1
                continue
            # Try to install it
            rc, _, _ = _run(
                ssh_cmd + [
                    "which apt-get >/dev/null 2>&1 && sudo apt-get install -y qemu-guest-agent >/dev/null 2>&1"
                    " || which dnf >/dev/null 2>&1 && sudo dnf install -y qemu-guest-agent >/dev/null 2>&1"
                    " || which zypper >/dev/null 2>&1 && sudo zypper install -y qemu-guest-agent >/dev/null 2>&1"
                    "; sudo systemctl enable --now qemu-guest-agent 2>/dev/null"
                ],
                timeout=60,
            )
            if rc == 0:
                installed_count += 1

        if installed_count:
            fmt.step_ok(f"Guest agent: {installed_count} newly installed, {already_count} already running")
        elif already_count:
            fmt.step_ok(f"Guest agent: all {already_count} VMs already have it")
        else:
            fmt.line(f"  {fmt.C.DIM}No VMs reachable for guest agent install.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.DIM}No VM hosts to install guest agent on.{fmt.C.RESET}")

    # ── 9e: LXC Container Discovery ──────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}LXC Container Discovery{fmt.C.RESET}")
    fmt.blank()

    if cfg.pve_nodes and key_path and os.path.isfile(key_path):
        lxc_count = 0
        # Query PVE API for LXC containers
        lxc_found = []
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            try:
                from freq.modules.pve import _pve_api_call
                result, ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/cluster/resources?type=vm")
                if ok and isinstance(result, list):
                    lxc_found = [v for v in result if v.get("type") == "lxc"]
            except Exception:
                pass

        if not lxc_found:
            # SSH fallback
            ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [f"{svc_name}@{cfg.pve_nodes[0]}"]
            rc, out, _ = _run(
                ssh_cmd + ["sudo pvesh get /cluster/resources --type vm --output-format json 2>/dev/null"],
                timeout=DEFAULT_CMD_TIMEOUT,
            )
            if rc == 0 and out.strip():
                try:
                    all_res = _json.loads(out)
                    lxc_found = [v for v in all_res if v.get("type") == "lxc"]
                except _json.JSONDecodeError:
                    pass

        if lxc_found:
            # Register LXC containers as hosts (if they have IPs via pct exec)
            from freq.core.config import Host, append_host_toml
            existing_ips = {h.ip for h in cfg.hosts}
            for ct in lxc_found:
                ctid = ct.get("vmid", 0)
                name = ct.get("name", "")
                node = ct.get("node", "")
                status = ct.get("status", "")
                if status != "running" or not name:
                    continue

                # Get CT IP via pct exec
                node_ip = cfg.pve_nodes[0]
                for i, pn in enumerate(getattr(cfg, "pve_node_names", []) or []):
                    if pn == node and i < len(cfg.pve_nodes):
                        node_ip = cfg.pve_nodes[i]
                        break

                ssh_cmd = ["ssh", "-n"] + ssh_base_opts + [f"{svc_name}@{node_ip}"]
                rc, out, _ = _run(
                    ssh_cmd + [f"sudo pct exec {ctid} -- hostname -I 2>/dev/null"],
                    timeout=QUICK_CHECK_TIMEOUT,
                )
                if rc == 0 and out.strip():
                    # Take first non-loopback IP
                    ct_ip = ""
                    for ip_str in out.strip().split():
                        if not ip_str.startswith("127."):
                            ct_ip = ip_str
                            break
                    if ct_ip and ct_ip not in existing_ips:
                        try:
                            from freq.core.validate import sanitize_label
                            safe_label = sanitize_label(name)
                        except ImportError:
                            safe_label = name.lower().replace(" ", "-")
                        host = Host(ip=ct_ip, label=safe_label, htype="linux", groups="lxc")
                        append_host_toml(cfg.hosts_file, host)
                        cfg.hosts.append(host)
                        existing_ips.add(ct_ip)
                        lxc_count += 1

            if lxc_count:
                fmt.step_ok(f"LXC: {lxc_count} containers discovered and registered")
            else:
                fmt.step_ok(f"LXC: {len(lxc_found)} found on PVE, all already registered or no IPs")
        else:
            fmt.line(f"  {fmt.C.DIM}No LXC containers found on PVE cluster.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.DIM}PVE not available for LXC discovery.{fmt.C.RESET}")

    # ── 9f: Cloud-Init Template Discovery ─────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Cloud-Init Template Discovery{fmt.C.RESET}")
    fmt.blank()

    if cfg.pve_nodes and key_path and os.path.isfile(key_path):
        templates = []
        # Query PVE for templates
        pve_vms_all = []
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            try:
                from freq.modules.pve import _pve_api_call
                result, ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/cluster/resources?type=vm")
                if ok and isinstance(result, list):
                    pve_vms_all = result
            except Exception:
                pass

        if pve_vms_all:
            templates = [v for v in pve_vms_all if v.get("template", 0) == 1]

        if templates:
            # Write discovered templates info
            distros_path = os.path.join(cfg.conf_dir, "distros.toml")
            try:
                lines = [
                    "# FREQ Distro Templates",
                    "# Auto-discovered from PVE cluster",
                    "",
                ]
                for t in sorted(templates, key=lambda x: x.get("vmid", 0)):
                    vmid = t.get("vmid", 0)
                    name = t.get("name", "unknown")
                    node = t.get("node", "")
                    safe = name.lower().replace(" ", "-").replace(".", "-")
                    lines.append(f"[template.{safe}]")
                    lines.append(f"vmid = {vmid}")
                    lines.append(f'name = "{name}"')
                    lines.append(f'node = "{node}"')
                    lines.append("")
                with open(distros_path, "w") as f:
                    f.write("\n".join(lines))
                fmt.step_ok(f"Templates: {len(templates)} cloud-init templates discovered")
            except OSError as e:
                fmt.step_warn(f"Could not write distros.toml: {e}")
        else:
            fmt.line(f"  {fmt.C.DIM}No cloud-init templates found.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.DIM}PVE not available for template discovery.{fmt.C.RESET}")

    # ── 9g: Protected VMs ─────────────────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Protected VMs{fmt.C.RESET}")
    fmt.blank()

    # Auto-protect: PVE nodes themselves, templates, and VMs in the 900-999 range
    protected_vmids = []
    protected_ranges = [[900, 999]]  # default: FREQ infra range
    if cfg.pve_nodes:
        pve_vms_for_protection = []
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            try:
                from freq.modules.pve import _pve_api_call
                result, ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/cluster/resources?type=vm")
                if ok and isinstance(result, list):
                    pve_vms_for_protection = result
            except Exception:
                pass
        # Protect templates automatically
        for v in pve_vms_for_protection:
            if v.get("template", 0) == 1:
                protected_vmids.append(v.get("vmid", 0))

    # Update freq.toml safety section
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    try:
        with open(toml_path) as f:
            content = f.read()
        if protected_vmids:
            content = _update_toml_value(content, "protected_vmids", protected_vmids)
        content = _update_toml_value(content, "protected_ranges", protected_ranges)
        with open(toml_path, "w") as f:
            f.write(content)
        total_protected = len(protected_vmids) + sum(hi - lo + 1 for lo, hi in protected_ranges)
        fmt.step_ok(f"Protected: {len(protected_vmids)} templates + VMID range 900-999")
    except OSError:
        pass

    # ── 9h: pfSense Configuration ─────────────────────────────────
    pfsense_ip = getattr(cfg, "pfsense_ip", "")
    if pfsense_ip:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}pfSense Integration{fmt.C.RESET}")
        fmt.blank()

        try:
            with open(toml_path) as f:
                content = f.read()
            # Write [pfsense] section if not present
            if "[pfsense]" not in content:
                content += (
                    "\n[pfsense]\n"
                    f'host = "{pfsense_ip}"\n'
                    f'user = "{svc_name}"\n'
                    'config_path = "/cf/conf/config.xml"\n'
                )
                with open(toml_path, "w") as f:
                    f.write(content)
            fmt.step_ok(f"pfSense configured: {pfsense_ip}")
        except OSError:
            pass

    # ── 9i: NIC Profiles from VLANs ──────────────────────────────
    vlans = getattr(cfg, "vlans", []) or []
    if vlans:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}NIC Profiles{fmt.C.RESET}")
        fmt.blank()

        try:
            with open(toml_path) as f:
                content = f.read()
            if "[nic.profiles]" not in content:
                vlan_ids = [v.id for v in vlans if hasattr(v, "id")]
                # Build profiles: standard = all VLANs, minimal = first VLAN only
                if vlan_ids:
                    all_str = str(vlan_ids)
                    min_str = str(vlan_ids[:1])
                    content += (
                        "\n[nic.profiles]\n"
                        f"standard = {all_str}\n"
                        f"minimal = {min_str}\n"
                    )
                    with open(toml_path, "w") as f:
                        f.write(content)
                    fmt.step_ok(f"NIC profiles: standard ({len(vlan_ids)} VLANs), minimal (1 VLAN)")
            else:
                fmt.step_ok("NIC profiles already configured")
        except OSError:
            pass

    # ── 9j: Notifications ─────────────────────────────────────────
    headless = getattr(cfg, "_headless", False)
    if not headless:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Notifications{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}FREQ can alert you via Discord, Slack, Telegram, email, ntfy, and more.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Configure later in freq.toml [notifications] section.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Or run: freq configure notifications{fmt.C.RESET}")

    # ── 9k: Dashboard Service ─────────────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Dashboard Service{fmt.C.RESET}")
    fmt.blank()

    dashboard_port = getattr(cfg, "dashboard_port", 8888)
    # Detect actual freq binary — check PATH, common locations, pip user installs
    freq_bin = shutil.which("freq")
    if not freq_bin:
        for candidate in ["/usr/local/bin/freq", "/usr/bin/freq",
                          os.path.expanduser("~/.local/bin/freq"),
                          f"/home/{svc_name}/.local/bin/freq"]:
            if os.path.isfile(candidate):
                freq_bin = candidate
                break
    if not freq_bin:
        fmt.step_warn("Cannot find 'freq' binary — dashboard service not installed")
    else:
        work_dir = cfg.install_dir or "/opt/pve-freq"
        service_unit = (
            "[Unit]\n"
            "Description=PVE FREQ Dashboard\n"
            "After=network.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={freq_bin} serve --port {dashboard_port}\n"
            "Restart=always\n"
            "RestartSec=10\n"
            "TimeoutStopSec=10\n"
            "KillMode=mixed\n"
            f"User={svc_name}\n"
            f"WorkingDirectory={work_dir}\n"
            f"Environment=FREQ_DIR={work_dir}\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        try:
            service_path = "/etc/systemd/system/freq-dashboard.service"
            with open(service_path, "w") as f:
                f.write(service_unit)
            _run(["systemctl", "daemon-reload"])
            _run(["systemctl", "enable", "freq-dashboard"])
            # Actually start the service — don't make the user guess
            rc_start, _, _ = _run(["systemctl", "start", "freq-dashboard"])
            if rc_start == 0:
                fmt.step_ok(f"Dashboard running on port {dashboard_port}")
            else:
                fmt.step_ok(f"Dashboard service installed (port {dashboard_port})")
                fmt.line(f"  {fmt.C.DIM}Start with: sudo systemctl start freq-dashboard{fmt.C.RESET}")
            audit.record("deploy_service", "local", "success", service="freq-dashboard")
        except OSError as e:
            fmt.step_warn(f"Could not install dashboard service: {e}")

    # ── 9l: Dashboard HTTPS ───────────────────────────────────────
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Dashboard TLS{fmt.C.RESET}")
    fmt.blank()

    cert_dir = os.path.join(os.path.dirname(cfg.conf_dir), "tls")
    cert_path = os.path.join(cert_dir, "freq.crt")
    key_path_tls = os.path.join(cert_dir, "freq.key")
    if not os.path.isfile(cert_path):
        os.makedirs(cert_dir, mode=0o700, exist_ok=True)
        # Generate self-signed cert
        rc, _, err = _run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path_tls, "-out", cert_path,
                "-days", "3650", "-nodes",
                "-subj", "/CN=freq-dashboard/O=PVE FREQ",
            ],
            timeout=DEFAULT_CMD_TIMEOUT,
        )
        if rc == 0:
            os.chmod(key_path_tls, 0o600)
            # Update freq.toml with TLS paths
            try:
                with open(toml_path) as f:
                    content = f.read()
                content = _update_toml_value(content, "tls_cert", cert_path)
                content = _update_toml_value(content, "tls_key", key_path_tls)
                with open(toml_path, "w") as f:
                    f.write(content)
                fmt.step_ok(f"Self-signed TLS cert generated (10-year, {cert_path})")
            except OSError:
                fmt.step_ok(f"TLS cert generated but could not update freq.toml")
        else:
            fmt.step_warn(f"Could not generate TLS cert: {err.strip()[:100]}")
    else:
        fmt.step_ok("TLS certificate already exists")

    # ── 9m: Fix ownership for dashboard ───────────────────────────
    # Dashboard runs as the service account. Init runs as root.
    # Every directory the dashboard needs must be owned by svc_name.
    install_dir = os.path.dirname(cfg.conf_dir)
    for subdir in ["data/keys", "data/log", "data/vault", "data/cache", "credentials", "tls"]:
        target = os.path.join(install_dir, subdir)
        if os.path.isdir(target):
            _chown(f"{svc_name}:{svc_name}", target, recursive=True)
    # conf/ must be readable by dashboard (freq.toml, hosts.toml, etc.)
    _chown(f"{svc_name}:{svc_name}", cfg.conf_dir, recursive=True)
    fmt.step_ok(f"Dashboard data directories owned by {svc_name}")
    logger.info("init_phase_complete: Phase 9 - fleet_configure", phase=9)


def _categorize_vms(cfg):
    """Auto-categorize VMs into fleet-boundary tiers.

    Uses VMID ranges, name patterns, and PVE tags.
    Returns dict of {category_name: {description, tier, vmids, range_start?, range_end?}}.
    """
    import json as _json

    if not cfg.pve_nodes:
        return {}

    # Query PVE for VM list
    pve_vms = []
    key_path = cfg.ssh_key_path
    svc_name = cfg.ssh_service_account

    if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
        try:
            from freq.modules.pve import _pve_api_call
            result, ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/cluster/resources?type=vm")
            if ok and isinstance(result, list):
                pve_vms = result
        except Exception:
            pass

    if not pve_vms and key_path and os.path.isfile(key_path):
        # SSH fallback
        rc, out, _ = _run(
            ["ssh", "-n", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "-i", key_path, f"{svc_name}@{cfg.pve_nodes[0]}",
             "sudo pvesh get /cluster/resources --type vm --output-format json 2>/dev/null"],
            timeout=DEFAULT_CMD_TIMEOUT,
        )
        if rc == 0 and out.strip():
            try:
                pve_vms = _json.loads(out)
            except _json.JSONDecodeError:
                pass

    if not pve_vms:
        return {}

    # Categorize VMs
    lab_vmids = []
    prod_vmids = []
    template_vmids = []
    infra_vmids = []

    for vm in pve_vms:
        vmid = vm.get("vmid", 0)
        name = (vm.get("name", "") or "").lower()
        tags = vm.get("tags", "") or ""
        template_flag = vm.get("template", 0)

        # Templates (PVE template flag or naming convention)
        if template_flag or "template" in name or name.startswith("tmpl-") or 9000 <= vmid < 9100:
            template_vmids.append(vmid)
            continue

        # Check tags first
        if "prod" in tags or "production" in tags:
            prod_vmids.append(vmid)
        elif "lab" in tags or "dev" in tags or "test" in tags:
            lab_vmids.append(vmid)
        # VMID range heuristics
        elif 5000 <= vmid < 5100:
            lab_vmids.append(vmid)
        elif 100 <= vmid < 200:
            infra_vmids.append(vmid)
        elif 200 <= vmid < 1000:
            prod_vmids.append(vmid)
        else:
            prod_vmids.append(vmid)

    categories = {}
    if prod_vmids:
        categories["production"] = {
            "description": "Production workloads",
            "tier": "operator",
            "vmids": sorted(prod_vmids),
            "range_start": None,
            "range_end": None,
        }
    if lab_vmids:
        categories["lab"] = {
            "description": "Lab and development VMs",
            "tier": "admin",
            "vmids": sorted(lab_vmids),
            "range_start": None,
            "range_end": None,
        }
    if template_vmids:
        categories["templates"] = {
            "description": "Clone sources — never start directly",
            "tier": "probe",
            "vmids": sorted(template_vmids),
            "range_start": None,
            "range_end": None,
        }
    if infra_vmids:
        categories["infrastructure"] = {
            "description": "Core infrastructure VMs",
            "tier": "probe",
            "vmids": sorted(infra_vmids),
            "range_start": None,
            "range_end": None,
        }

    return categories


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
            full = base + ["-o", "BatchMode=yes", "-i", auth_key, f"{auth_user}@{ip}", cmd]
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
    logger.info(f"deploy_start: {ip} [{htype}]", host=ip, htype=htype)

    # Dry-run: show what would be done without making changes
    if ctx.get("dry_run"):
        fmt.step_info(f"DRY RUN: Would deploy {svc_name} to {ip}")
        logger.info("dry_run_deploy", host=ip, htype=htype, user=svc_name)
        audit.record("deploy_user", ip, "dry_run", user=svc_name)
        return True

    # Sanitize pubkey — escape single quotes for safe shell embedding
    pubkey = pubkey.replace("'", "'\\''") if pubkey else ""

    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({_ssh_error_msg(rc, err)})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=_ssh_error_msg(rc, err))
        audit.record("deploy_user", ip, "failed", user=svc_name, error="connect_failed")
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
        logger.error(f"deploy_failed: {ip}", host=ip, error="useradd_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="useradd")
        return False
    elif "SUDOERS_FAIL" in out:
        fmt.step_fail("Sudoers validation failed")
        logger.error(f"deploy_failed: {ip}", host=ip, error="sudoers_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="sudoers")
        return False
    elif MARKER_DEPLOY_OK not in out:
        fmt.step_fail(f"Deploy script failed ({err[:60]})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=err[:120])
        audit.record("deploy_user", ip, "failed", user=svc_name, error="script_failed")
        return False

    # Report chpasswd status
    if MARKER_CHPASSWD_FAIL in out:
        fmt.step_warn("Password set failed — account may be locked")
    else:
        fmt.step_ok("Account, password, sudo, SSH key deployed")

    # Verify FREQ key SSH access
    success = True
    if ctx.get("key_path") and os.path.isfile(ctx["key_path"]):
        rc2, _, _ = _run(
            [
                "ssh",
                "-n",
                "-i",
                ctx["key_path"],
                "-o",
                "ConnectTimeout=3",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{svc_name}@{ip}",
                "echo OK",
            ]
        )
        if rc2 == 0:
            fmt.step_ok(f"Verified: FREQ key SSH as {svc_name}")
        else:
            fmt.step_fail(f"FREQ key login FAILED as {svc_name} — check sshd + authorized_keys")
            success = False

        # Verify sudo works
        if rc2 == 0:
            rc3, _, _ = _run(
                [
                    "ssh",
                    "-n",
                    "-i",
                    ctx["key_path"],
                    "-o",
                    "ConnectTimeout=3",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    f"{svc_name}@{ip}",
                    "sudo -n true",
                ]
            )
            if rc3 == 0:
                fmt.step_ok(f"Verified: NOPASSWD sudo works as {svc_name}")
            else:
                fmt.step_fail(f"SUDO FAILED — {svc_name} cannot sudo on {ip}")
                success = False

    if success:
        logger.info(f"deploy_success: {ip}", host=ip)
        audit.record("deploy_user", ip, "success", user=svc_name, method="useradd")
    else:
        logger.error(f"deploy_failed: {ip}", host=ip, error="verification_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="verification")
    return success


def _deploy_pfsense(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to pfSense (FreeBSD).

    Uses pw useradd. No sudo (pfSense admin model). ed25519 key.
    Returns True on success.
    """
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    pubkey = ctx["pubkey"]
    logger.info(f"deploy_start: {ip} [pfsense]", host=ip, htype="pfsense")

    # Dry-run: show what would be done without making changes
    if ctx.get("dry_run"):
        fmt.step_info(f"DRY RUN: Would deploy {svc_name} to {ip}")
        logger.info("dry_run_deploy", host=ip, htype="pfsense", user=svc_name)
        audit.record("deploy_user", ip, "dry_run", user=svc_name)
        return True

    # Sanitize pubkey — escape single quotes for safe shell embedding
    pubkey = pubkey.replace("'", "'\\''") if pubkey else ""

    # pfSense: admin IS root (UID 0). No sudo available on FreeBSD/pfSense.
    # Auth user must be root or admin for user creation to work.
    if auth_user not in ("root", "admin"):
        fmt.step_warn(f"pfSense auth as '{auth_user}' — may lack privilege (root/admin required for pw useradd)")

    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("echo OK")
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({_ssh_error_msg(rc, err)})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=_ssh_error_msg(rc, err))
        audit.record("deploy_user", ip, "failed", user=svc_name, error="connect_failed")
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
        logger.error(f"deploy_failed: {ip}", host=ip, error="useradd_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="useradd")
        return False
    elif MARKER_DEPLOY_OK not in out:
        fmt.step_fail(f"Deploy script failed ({err[:60]})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=err[:120])
        audit.record("deploy_user", ip, "failed", user=svc_name, error="script_failed")
        return False

    if MARKER_CHPASSWD_FAIL in out:
        fmt.step_warn("Password set failed on pfSense")
    else:
        fmt.step_ok("Account, password, SSH key deployed (no sudo — pfSense)")

    # Verify FREQ key SSH access (no sudo on pfSense)
    success = True
    if ctx.get("key_path") and os.path.isfile(ctx["key_path"]):
        rc2, _, _ = _run(
            [
                "ssh",
                "-n",
                "-i",
                ctx["key_path"],
                "-o",
                "ConnectTimeout=3",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{svc_name}@{ip}",
                "echo OK",
            ]
        )
        if rc2 == 0:
            fmt.step_ok(f"Verified: FREQ key SSH as {svc_name}")
        else:
            fmt.step_fail(f"FREQ key login FAILED as {svc_name}")
            success = False

    if success:
        logger.info(f"deploy_success: {ip}", host=ip)
        audit.record("deploy_user", ip, "success", user=svc_name, method="pw_useradd")
    else:
        logger.error(f"deploy_failed: {ip}", host=ip, error="verification_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="verification")
    return success


def _deploy_idrac(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to Dell iDRAC.

    Uses racadm commands. RSA key only. Password auth for initial connect.
    Bounded by DEVICE_DEPLOY_TIMEOUT to prevent indefinite hangs.
    Returns True on success.
    """
    deploy_start = time.monotonic()
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    rsa_pubkey = ctx.get("rsa_pubkey", "")
    logger.info(f"deploy_start: {ip} [idrac]", host=ip, htype="idrac")

    def _check_timeout(step=""):
        elapsed = time.monotonic() - deploy_start
        if elapsed > DEVICE_DEPLOY_TIMEOUT:
            fmt.step_fail(f"iDRAC deploy timeout ({elapsed:.0f}s > {DEVICE_DEPLOY_TIMEOUT}s) at {step}")
            logger.error(f"deploy_timeout: {ip}", host=ip, elapsed=elapsed, step=step)
            return True
        return False

    # Dry-run: show what would be done without making changes
    if ctx.get("dry_run"):
        fmt.step_info(f"DRY RUN: Would deploy {svc_name} to {ip}")
        logger.info("dry_run_deploy", host=ip, htype="idrac", user=svc_name)
        audit.record("deploy_user", ip, "dry_run", user=svc_name)
        return True

    if not rsa_pubkey:
        fmt.step_fail("No RSA public key — iDRAC requires RSA (not ed25519)")
        return False

    # iDRAC requires legacy ciphers
    extra_opts = PLATFORM_SSH.get("idrac", {}).get("extra_opts", [])
    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity with legacy ciphers
    rc, out, err = _ssh("racadm getsysinfo", extra_opts=extra_opts)
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({_ssh_error_msg(rc, err)})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=_ssh_error_msg(rc, err))
        audit.record("deploy_user", ip, "failed", user=svc_name, error="connect_failed")
        return False
    fmt.step_ok("Connected to iDRAC")

    if _check_timeout("slot_query"):
        return False

    # Find an empty user slot (slots 3-16, 1-2 are reserved)
    target_slot, existing_slot = _query_idrac_slots(_ssh, extra_opts, svc_name)

    if _check_timeout("after_slot_query"):
        return False

    if existing_slot:
        fmt.step_ok(f"Account '{svc_name}' already in slot {existing_slot}")
        target_slot = existing_slot
    elif target_slot:
        fmt.step_ok(f"Using empty slot {target_slot}")
    else:
        fmt.step_fail("No empty iDRAC user slots (3-16 all occupied)")
        return False

    # Create/update user in target slot
    setup_cmds = (
        f"racadm set iDRAC.Users.{target_slot}.UserName {svc_name}",
        f"racadm set iDRAC.Users.{target_slot}.Password {svc_pass}",
        f"racadm set iDRAC.Users.{target_slot}.Privilege 0x1ff",
        f"racadm set iDRAC.Users.{target_slot}.Enable 1",
        f"racadm set iDRAC.Users.{target_slot}.IpmiLanPrivilege 4",
    )
    for cmd in setup_cmds:
        if _check_timeout("user_setup"):
            return False
        ok_cmd, details = _run_idrac_command(_ssh, extra_opts, cmd, timeout=IDRAC_SETUP_TIMEOUT)
        if not ok_cmd:
            fmt.step_fail(f"iDRAC user setup failed ({details.strip()[:80]})")
            logger.error(f"deploy_failed: {ip}", host=ip, error="idrac_setup_failed")
            audit.record("deploy_user", ip, "failed", user=svc_name, error="racadm_setup")
            return False
    fmt.step_ok(f"iDRAC user '{svc_name}' configured (slot {target_slot})")

    if _check_timeout("key_deploy"):
        return False

    # Deploy RSA public key
    ok_cmd, details = _run_idrac_command(
        _ssh,
        extra_opts,
        f'racadm sshpkauth -i {target_slot} -k 1 -t "{rsa_pubkey}"',
        timeout=30,
    )
    if not ok_cmd:
        fmt.step_fail(f"RSA key upload failed ({details.strip()[:60]})")
        fmt.step_warn("iDRAC user created but key-based SSH won't work — password auth only")
        logger.error(f"deploy_failed: {ip}", host=ip, error="rsa_key_upload_failed")
        audit.record("deploy_user", ip, "failed", user=svc_name, error="rsa_key_upload")
        return False

    # Verify the key was actually stored
    rc2, out2, err2 = _ssh(
        f"racadm sshpkauth -v -i {target_slot} -k 1",
        extra_opts=extra_opts,
        timeout=IDRAC_VERIFY_TIMEOUT,
    )
    if rc2 == 0 and out2.strip() and "failed" not in (out2 + err2).lower():
        fmt.step_ok("RSA public key deployed and verified on iDRAC")
    else:
        fmt.step_warn("RSA key uploaded but verification query failed — check manually")

    logger.info(f"deploy_success: {ip}", host=ip)
    audit.record("deploy_user", ip, "success", user=svc_name, method="racadm")
    return True


def _deploy_switch(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy service account to Cisco IOS switch.

    Uses IOS config commands. RSA key only. Password auth for initial connect.
    Bounded by DEVICE_DEPLOY_TIMEOUT to prevent indefinite hangs.
    Returns True on success.
    """
    deploy_start = time.monotonic()
    svc_name = ctx["svc_name"]
    svc_pass = ctx["svc_pass"]
    rsa_pubkey = ctx.get("rsa_pubkey", "")
    logger.info(f"deploy_start: {ip} [switch]", host=ip, htype="switch")

    # Dry-run: show what would be done without making changes
    if ctx.get("dry_run"):
        fmt.step_info(f"DRY RUN: Would deploy {svc_name} to {ip}")
        logger.info("dry_run_deploy", host=ip, htype="switch", user=svc_name)
        audit.record("deploy_user", ip, "dry_run", user=svc_name)
        return True

    if not rsa_pubkey:
        fmt.step_fail("No RSA public key — switch requires RSA (not ed25519)")
        return False

    # Switch requires legacy ciphers
    extra_opts = PLATFORM_SSH.get("switch", {}).get("extra_opts", [])
    _ssh = _init_ssh(ip, auth_pass, auth_key, auth_user)

    # Test connectivity
    rc, out, err = _ssh("show version | include uptime", extra_opts=extra_opts)
    if rc != 0:
        fmt.step_fail(f"Cannot connect ({_ssh_error_msg(rc, err)})")
        logger.error(f"deploy_failed: {ip}", host=ip, error=_ssh_error_msg(rc, err))
        audit.record("deploy_user", ip, "failed", user=svc_name, error="connect_failed")
        return False
    fmt.step_ok("Connected to switch")

    # Build IOS config commands — create user + deploy RSA public key
    # RSA public key base64 data split into 72-char lines (PEM width).
    # IOS key-string chokes on 254-char lines — 72 works reliably.
    rsa_key_data = rsa_pubkey.split(" ")[1] if " " in rsa_pubkey else rsa_pubkey
    key_lines = [rsa_key_data[i : i + IOS_KEY_LINE_WIDTH] for i in range(0, len(rsa_key_data), IOS_KEY_LINE_WIDTH)]

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
    ios_cmds.extend(
        [
            "exit",  # exit key-string → username
            "exit",  # exit username → pubkey-chain
            "exit",  # exit pubkey-chain → config
            "exit",  # exit config → exec mode
            "write memory",  # save config (exec mode only)
        ]
    )

    # Pipe IOS commands via stdin — IOS requires interactive-style input
    # for config mode (configure terminal). SSH exec args don't work for
    # multi-command config sessions. Uses ssh -T (no pseudo-tty).
    ios_cmds.append("exit")  # exit exec mode to close session cleanly
    ios_script = "\n".join(ios_cmds) + "\n"

    ssh_cmd = [
        "ssh",
        "-T",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if extra_opts:
        ssh_cmd.extend(extra_opts)
    ssh_cmd.append(f"{auth_user}@{ip}")

    if auth_pass:
        rc, out, err = _ssh_with_pass(auth_pass, ssh_cmd, timeout=30, input_text=ios_script)
    elif auth_key:
        ssh_cmd.extend(["-o", "BatchMode=yes", "-i", auth_key])
        rc, out, err = _run_with_input(ssh_cmd, ios_script, timeout=30)
    else:
        rc, out, err = _run_with_input(ssh_cmd, ios_script, timeout=30)

    # IOS doesn't give clean exit codes — check for specific error indicators.
    # Generic "error" matching is too broad — IOS echoes "error" in normal output.
    out_lower = (out or "").lower()
    ios_errors = [
        "% invalid input detected",  # bad command syntax
        "% incomplete command",  # missing args
        "% ambiguous command",  # ambiguous abbreviation
        "% authorization failed",  # AAA rejection
        "% authentication failed",  # login failure
        "% bad ip address",  # invalid IP
        "% invalid username",  # user creation failure
        "%ssh-4-badpkauth",  # key auth failure (syslog)
    ]
    key_warnings = [
        "%ssh: failed to decode",  # bad key data (base64/format)
        "failed to decode the key",
    ]

    # Hard errors — config definitely failed
    for pat in ios_errors:
        if pat in out_lower:
            fmt.step_fail(f"IOS config failed: {pat.strip('% ')} ({out.strip()[:80]})")
            logger.error(f"deploy_failed: {ip}", host=ip, error=f"ios_{pat.strip('% ')}")
            audit.record("deploy_user", ip, "failed", user=svc_name, error="ios_config")
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

    logger.info(f"deploy_success: {ip}", host=ip)
    audit.record("deploy_user", ip, "success", user=svc_name, method="ios_config")
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
            "ssh",
            "-n",
            "-i",
            key_path,
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
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
    _, target_slot = _query_idrac_slots(_ssh, extra_opts, svc_name)
    # In removal, we want the existing slot (not the empty one)
    # _parse_idrac_slots returns (empty_slot, existing_slot)

    if not target_slot:
        return True, "not_found"  # Already gone

    remove_cmds = (
        f"racadm set iDRAC.Users.{target_slot}.Enable 0",
        f'racadm set iDRAC.Users.{target_slot}.UserName ""',
        f'racadm sshpkauth -i {target_slot} -k 1 -t ""',
    )
    for cmd in remove_cmds:
        ok_cmd, details = _run_idrac_command(_ssh, extra_opts, cmd, timeout=30)
        if not ok_cmd:
            return False, f"removal failed: {details.strip()[:80]}"

    return True, ""


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

    # IOS removal commands — must be sent via stdin for configure terminal
    ios_cmds = [
        "configure terminal",
        f"no username {svc_name}",
        "ip ssh pubkey-chain",
        f"  no username {svc_name}",
        "  exit",
        "exit",
        "write memory",
    ]
    ios_script = "\n".join(ios_cmds) + "\n"
    # Use subprocess directly with stdin for IOS config mode
    ssh_cmd = [
        "ssh",
        "-T",
        "-i",
        key_path,
        "-o",
        "ConnectTimeout=5",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if extra_opts:
        ssh_cmd.extend(extra_opts)
    ssh_cmd.append(f"{svc_name}@{ip}")
    proc = subprocess.run(ssh_cmd, input=ios_script, capture_output=True, text=True, timeout=30)
    rc, out, err = proc.returncode, proc.stdout, proc.stderr

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
# PHASE 11: Admin Account Setup
# ═══════════════════════════════════════════════════════════════════


def _phase_admin_setup(cfg, ctx):
    """Configure RBAC roles."""
    logger.info("init_phase_start: Phase 11 - admin_setup", phase=11)
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")

    # Ensure file exists
    if not os.path.isfile(roles_file):
        open(roles_file, "a").close()

    # Current user
    current_user = os.environ.get("SUDO_USER", os.environ.get("USER", "root"))
    fmt.line(f"  {fmt.C.DIM}Current user: {fmt.C.BOLD}{current_user}{fmt.C.RESET}")
    fmt.blank()

    def _active_roles(path):
        """Read roles.conf and return only uncommented entries."""
        if not os.path.isfile(path):
            return []
        with open(path) as f:
            return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    # Add current user as admin
    active = _active_roles(roles_file)
    if any(l.startswith(f"{current_user}:") for l in active):
        fmt.step_ok(f"{current_user} already in roles.conf")
    else:
        with open(roles_file, "a") as f:
            f.write(f"{current_user}:admin\n")
        fmt.step_ok(f"Added {current_user} as admin")

    # Add service account as admin
    svc_name = ctx["svc_name"]
    active = _active_roles(roles_file)
    if not any(l.startswith(f"{svc_name}:") for l in active):
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

            active = _active_roles(roles_file)
            if any(l.startswith(f"{username}:") for l in active):
                fmt.line(f"  {fmt.C.DIM}{username} already in roles.conf{fmt.C.RESET}")
            else:
                with open(roles_file, "a") as f:
                    f.write(f"{username}:{role}\n")
                fmt.step_ok(f"Added {username} as {role}")

    logger.info("init_phase_complete: Phase 11 - admin_setup", phase=11)


# ═══════════════════════════════════════════════════════════════════
# PHASE 12: Verification
# ═══════════════════════════════════════════════════════════════════


def _is_skip_error(err):
    """Check if SSH error is a skip-worthy condition (not a real failure)."""
    err_l = err.lower()
    return any(
        s in err_l
        for s in [
            "no route to host",
            "network is unreachable",
            "connection timed out",
            "connection refused",
            "permission denied",
            "authentication",
            "host key verification failed",
        ]
    )


def _skip_reason(err):
    """Return a human-readable reason for skipping a host.

    More specific than just "unreachable" — the underlying error helps
    operators distinguish routing/firewall/host-down cases.
    """
    err_l = err.lower()
    if "no route to host" in err_l:
        return "no route to host (check VLAN/routing)"
    if "network is unreachable" in err_l:
        return "network unreachable (no route configured)"
    if "connection timed out" in err_l:
        return "connection timed out (host down or firewalled)"
    if "connection refused" in err_l:
        return "connection refused (SSH port closed)"
    if "permission denied" in err_l or "authentication" in err_l:
        return "auth failed"
    if "host key verification" in err_l:
        return "host key mismatch"
    return "SSH error"


def _verify_host(ip, htype, svc_name, key_path, rsa_key_path, cfg=None):
    """Platform-aware host verification. Returns (success, error_stderr).

    For legacy devices (iDRAC/switch), falls back to sshpass password auth
    if cfg.legacy_password_file is configured and key auth fails.
    """
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

    if not key or not os.path.isfile(key) or not os.access(key, os.R_OK):
        # For legacy devices, missing key is OK if password file exists
        if htype not in ("idrac", "switch"):
            reason = "not readable" if key and os.path.isfile(key) else "not found"
            return False, f"key {reason}: {key}"

    ssh_cmd = (
        [
            "ssh",
            "-n",
            "-i",
            key,
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
        + extra_opts
        + [f"{svc_name}@{ip}", verify_cmd]
    )

    rc, out, err = _run(ssh_cmd, timeout=VERIFY_TIMEOUT)
    # iDRAC has a 2-session SSH limit — retry once after a short wait
    if rc != 0 and htype in ("idrac", "switch") and "no more sessions" in (out + err).lower():
        time.sleep(5)
        rc, out, err = _run(ssh_cmd, timeout=VERIFY_TIMEOUT)

    # If key auth failed for legacy device, try sshpass with password file
    if rc != 0 and htype in ("idrac", "switch") and cfg:
        pw_file = getattr(cfg, "legacy_password_file", "") or ""
        if pw_file and os.path.isfile(pw_file):
            sshpass_cmd = (
                ["sshpass", "-f", pw_file, "ssh", "-n",
                 "-o", "ConnectTimeout=5",
                 "-o", "StrictHostKeyChecking=accept-new"]
                + extra_opts
                + [f"{svc_name}@{ip}", verify_cmd]
            )
            rc, out, err = _run(sshpass_cmd, timeout=VERIFY_TIMEOUT)
            if rc != 0 and "no more sessions" in (out + err).lower():
                time.sleep(5)
                rc, out, err = _run(sshpass_cmd, timeout=VERIFY_TIMEOUT)

    return rc == 0, (err or out)


def _phase_verify(cfg, ctx):
    """Verify all init steps completed. Returns True if all pass."""
    logger.info("init_phase_start: Phase 12 - verify", phase=12)
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

    # SSH keys — check init-generated keys AND resolved runtime key
    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")
    # Use resolved key for fleet verification (may be fleet_key or ~/.ssh/)
    resolved_key = cfg.ssh_key_path if cfg.ssh_key_path else key_file
    _check("FREQ ed25519 key exists (modern hosts)",
           os.path.isfile(key_file) or (cfg.ssh_key_path and os.path.isfile(cfg.ssh_key_path)))
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

    # Hosts — verify disk file exists and is parseable, not just memory state
    hosts_path = cfg.hosts_file if hasattr(cfg, "hosts_file") else os.path.join(cfg.conf_dir, "hosts.toml")
    hosts_file_ok = False
    if os.path.isfile(hosts_path):
        if tomllib:
            try:
                with open(hosts_path, "rb") as f:
                    tomllib.load(f)
                hosts_file_ok = True
            except Exception:
                pass
        else:
            hosts_file_ok = True
    if cfg.hosts and hosts_file_ok:
        _check(f"hosts.toml: {len(cfg.hosts)} hosts (file valid)", True)
    elif cfg.hosts and not hosts_file_ok:
        _check(f"hosts.toml: {len(cfg.hosts)} in memory but file missing or malformed", False)
    else:
        fmt.step_warn("hosts.toml is empty — use 'freq host add' or 'freq host discover'")

    # Timezone
    tz = "unknown"
    try:
        rc, out, _ = _run(["timedatectl", "show", "--property=Timezone", "--value"])
        if rc == 0:
            tz = out.strip()
    except (OSError, FileNotFoundError):
        pass  # timedatectl may not be available on all systems
    fmt.line(f"  {fmt.C.GREEN}✔{fmt.C.RESET} Timezone: {tz}")

    # PVE connectivity — use resolved key (may be fleet_key if init key missing)
    warns = 0
    verify_key = resolved_key if os.path.isfile(resolved_key) else key_file
    if cfg.pve_nodes and os.path.isfile(verify_key):
        for ip in cfg.pve_nodes:
            ok, err = _verify_host(ip, "pve", svc_name, verify_key, rsa_file, cfg=cfg)
            if ok:
                _check(f"PVE {ip}: SSH + sudo as {svc_name}", True)
            elif _is_skip_error(err):
                fmt.step_warn(f"PVE {ip}: {_skip_reason(err)} (skipped)")
                warns += 1
            else:
                _check(f"PVE {ip}: SSH + sudo as {svc_name}", False)

    # Fleet host connectivity — ALL platform types
    deployed_ips = ctx.get("deployed_ips", set())
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

            ok, err = _verify_host(h.ip, h.htype, svc_name, verify_key, rsa_file, cfg=cfg)
            if ok:
                _check(check_label, True)
            elif h.ip in deployed_ips:
                # We JUST deployed to this host — auth/skip errors are real failures
                _check(f"{check_label} — {_skip_reason(err)}", False)
            elif _is_skip_error(err):
                fmt.step_warn(f"Fleet {h.label} ({h.ip}): {_skip_reason(err)} (skipped)")
                warns += 1
            else:
                _check(check_label, False)

    # ── Enhanced checks (new phases) ──

    # PVE API Token
    if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
        try:
            from freq.modules.pve import _pve_api_call
            _, api_ok = _pve_api_call(cfg, cfg.pve_nodes[0], "/version")
            _check("PVE API token: REST API reachable", api_ok)
        except Exception:
            _check("PVE API token: REST API reachable", False)
    else:
        fmt.step_warn("PVE API token not configured — dashboard metrics will use SSH fallback")

    # vlans.toml populated
    vlans = getattr(cfg, "vlans", []) or []
    if vlans:
        _check(f"vlans.toml: {len(vlans)} VLANs discovered", True)
    else:
        fmt.step_warn("vlans.toml is empty — run 'freq host discover' to scan VLANs")

    # fleet-boundaries.toml — verify file is parseable TOML with real entries
    fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")
    fb_ok = False
    fb_msg = ""
    if os.path.isfile(fb_path):
        if tomllib:
            try:
                with open(fb_path, "rb") as f:
                    fb_data = tomllib.load(f)
                phys = fb_data.get("physical", {})
                pve = fb_data.get("pve_nodes", {})
                cats = {k: v for k, v in fb_data.items() if k.startswith("categories") or (k == "categories" and isinstance(v, dict))}
                cat_count = len(fb_data.get("categories", {})) if isinstance(fb_data.get("categories"), dict) else 0
                entry_count = len(phys) + len(pve) + cat_count
                if entry_count > 0:
                    fb_ok = True
                    fb_msg = f"{len(phys)} physical, {len(pve)} PVE, {cat_count} categories"
            except Exception:
                fb_msg = "malformed TOML"
        else:
            try:
                with open(fb_path) as f:
                    c = f.read()
                fb_ok = "[physical]" in c or "[pve_nodes]" in c or "[categories." in c
                fb_msg = "sections present"
            except OSError:
                pass
    if fb_ok:
        _check(f"fleet-boundaries.toml: {fb_msg}", True)
    elif fb_msg:
        _check(f"fleet-boundaries.toml: {fb_msg}", False)
    else:
        fmt.step_warn("fleet-boundaries.toml is empty — no device categories configured")

    # containers.toml — verify file is parseable if it was generated
    ct_path = os.path.join(cfg.conf_dir, "containers.toml")
    docker_hosts = [h for h in cfg.hosts if h.htype == "docker"] if cfg.hosts else []
    if os.path.isfile(ct_path):
        ct_ok = False
        ct_msg = ""
        if tomllib:
            try:
                with open(ct_path, "rb") as f:
                    ct_data = tomllib.load(f)
                host_section = ct_data.get("host", {})
                total_ct = sum(len(v.get("containers", {})) for v in host_section.values() if isinstance(v, dict))
                ct_ok = len(host_section) > 0
                ct_msg = f"{total_ct} containers across {len(host_section)} hosts"
            except Exception:
                ct_msg = "malformed TOML"
        else:
            ct_ok = True
            ct_msg = "file present"
        if ct_ok:
            _check(f"containers.toml: {ct_msg}", True)
        else:
            _check(f"containers.toml: {ct_msg}", False)
    elif docker_hosts:
        fmt.step_warn(f"containers.toml missing — {len(docker_hosts)} docker host(s) expected it")

    # freq.toml [infrastructure]
    infra_configured = any([
        getattr(cfg, "pfsense_ip", ""),
        getattr(cfg, "truenas_ip", ""),
        getattr(cfg, "switch_ip", ""),
    ])
    if infra_configured:
        _check("freq.toml [infrastructure]: devices configured", True)
    else:
        fmt.step_warn("freq.toml [infrastructure] is empty — no infrastructure IPs detected")

    # Metrics agent spot-check (first linux host)
    linux_hosts = [h for h in cfg.hosts if h.htype in ("linux", "docker")]
    if linux_hosts and key_file and os.path.isfile(key_file):
        test_host = linux_hosts[0]
        agent_port = getattr(cfg, "agent_port", 9990) or 9990
        rc_agent, out_agent, _ = _run(
            ["ssh", "-n", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
             "-i", key_file, f"{svc_name}@{test_host.ip}",
             f"curl -s http://localhost:{agent_port}/health 2>/dev/null"],
            timeout=QUICK_CHECK_TIMEOUT,
        )
        agent_ok = rc_agent == 0 and "ok" in out_agent.lower()
        if agent_ok:
            _check(f"Metrics agent responding on {test_host.label}", True)
        else:
            fmt.step_warn(f"Metrics agent not responding on {test_host.label} — may need manual start")

    # Dashboard readiness
    dashboard_ready = bool(
        getattr(cfg, "pve_api_token_id", "")
        and cfg.hosts
        and cfg.pve_nodes
    )
    _check("Dashboard readiness: token + hosts + nodes", dashboard_ready)

    fleet_deploy_failures = int(ctx.get("fleet_deploy_failures", 0) or 0)
    if fleet_deploy_failures:
        _check(f"Phase 8 fleet deployment: 0 failed hosts (saw {fleet_deploy_failures})", False)

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
        logger.info("init_phase_complete: Phase 12 - verify", phase=12, passes=passes, fails=fails, warns=warns)
        return True
    else:
        fmt.step_fail(f"NOT initialized ({fails} failures — fix and re-run 'freq init')")
        logger.error("init_phase_failed: Phase 12 - verify", phase=12, passes=passes, fails=fails, warns=warns)
        return False


# ═══════════════════════════════════════════════════════════════════
# PHASE 13: Summary
# ═══════════════════════════════════════════════════════════════════


def _phase_summary(cfg, ctx, verified, pack=None):
    """Print summary and next steps — enhanced with fleet topology."""
    logger.info("init_phase_start: Phase 13 - summary", phase=13)
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

    # Deployment scorecard
    deployed_count = len(ctx.get("deployed_ips", set()))
    deploy_failures = ctx.get("fleet_deploy_failures", 0)
    total_hosts = len(cfg.hosts)
    skipped = total_hosts - deployed_count - deploy_failures
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Deployment:{fmt.C.RESET}")
    fmt.line(f"    {fmt.C.GREEN}{deployed_count} deployed{fmt.C.RESET}, "
             f"{fmt.C.RED}{deploy_failures} failed{fmt.C.RESET}, "
             f"{fmt.C.YELLOW}{skipped} skipped{fmt.C.RESET} "
             f"({total_hosts} total hosts)")

    # Fleet topology
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Fleet Topology:{fmt.C.RESET}")
    fmt.line(f"    PVE Nodes:       {len(cfg.pve_nodes) if cfg.pve_nodes else 0}")
    vlans = getattr(cfg, "vlans", []) or []
    fmt.line(f"    VLANs:           {len(vlans)}")
    fmt.line(f"    Fleet Hosts:     {len(cfg.hosts)}")

    # Type breakdown
    if cfg.hosts:
        type_counts = {}
        for h in cfg.hosts:
            type_counts[h.htype] = type_counts.get(h.htype, 0) + 1
        for htype, count in sorted(type_counts.items()):
            fmt.line(f"      {htype:14s} {count}")

    # Infrastructure
    pfsense_ip = getattr(cfg, "pfsense_ip", "")
    truenas_ip = getattr(cfg, "truenas_ip", "")
    switch_ip = getattr(cfg, "switch_ip", "")
    if pfsense_ip or truenas_ip or switch_ip:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Infrastructure:{fmt.C.RESET}")
        if pfsense_ip:
            fmt.line(f"    Firewall:  {pfsense_ip}")
        if truenas_ip:
            fmt.line(f"    NAS:       {truenas_ip}")
        if switch_ip:
            fmt.line(f"    Switch:    {switch_ip}")

    # API status
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}API Access:{fmt.C.RESET}")
    token_id = getattr(cfg, "pve_api_token_id", "")
    api_verified = ctx.get("api_token_verified", False)
    if token_id and api_verified:
        fmt.line(f"    PVE API:   {fmt.C.GREEN}verified{fmt.C.RESET} ({token_id})")
    elif token_id:
        fmt.line(f"    PVE API:   {fmt.C.YELLOW}configured (unverified){fmt.C.RESET} ({token_id}) — will fall back to SSH")
    else:
        fmt.line(f"    PVE API:   {fmt.C.YELLOW}SSH-only{fmt.C.RESET} (no token configured)")

    # Component ports
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Services:{fmt.C.RESET}")
    tls_cert = getattr(cfg, "tls_cert", "")
    dash_scheme = "https" if tls_cert and os.path.isfile(tls_cert) else "http"
    fmt.line(f"    Dashboard: {dash_scheme}://localhost:{getattr(cfg, 'dashboard_port', 8888)}")
    fmt.line(f"    Watchdog:  port {getattr(cfg, 'watchdog_port', 9900)}")
    fmt.line(f"    Agent:     port {getattr(cfg, 'agent_port', 9990)}")

    # Next steps
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Next steps:{fmt.C.RESET}")
    if deploy_failures:
        fmt.line(f"    freq init --fix      — {fmt.C.YELLOW}retry {deploy_failures} failed host(s){fmt.C.RESET}")
    fmt.line(f"    freq serve           — start the dashboard")
    fmt.line(f"    freq fleet status    — check fleet connectivity")
    fmt.line(f"    freq vm list         — see all VMs across cluster")
    fmt.line(f"    freq doctor          — verify FREQ is healthy")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Dashboard login: first login sets your password (any password accepted).{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}Break-glass access: su - {svc_name}{fmt.C.RESET}")
    fmt.blank()

    # Celebrate
    if pack:
        from freq.core.personality import celebrate

        msg = celebrate(pack)
        if msg:
            fmt.line(f"  {fmt.C.DIM}{msg}{fmt.C.RESET}")

    logger.info("init_phase_complete: Phase 13 - summary", phase=13, verified=verified)
    fmt.footer()


# ═══════════════════════════════════════════════════════════════════
# --check mode
# ═══════════════════════════════════════════════════════════════════


def _scan_fleet(cfg):
    """Test service account SSH to all hosts. Returns (ok_list, fail_list, unreachable_list).

    Each entry is a dict: {host, ip, htype, error}.
    Shared by --check and --fix.
    """
    import concurrent.futures

    svc_name = cfg.ssh_service_account
    # Use the resolved key path (may be fleet_key, not just key_dir/freq_id_ed25519)
    key_file = cfg.ssh_key_path
    rsa_file = cfg.ssh_rsa_key_path if hasattr(cfg, "ssh_rsa_key_path") else os.path.join(cfg.key_dir, "freq_id_rsa")

    pve_set = set(cfg.pve_nodes) if cfg.pve_nodes else set()
    all_hosts = []

    # PVE nodes
    for ip in cfg.pve_nodes or []:
        all_hosts.append({"label": ip, "ip": ip, "htype": "pve"})

    # Fleet hosts (skip PVE nodes already covered, skip unmanaged hosts)
    for h in cfg.hosts:
        if h.ip not in pve_set and getattr(h, "managed", True):
            all_hosts.append({"label": h.label, "ip": h.ip, "htype": h.htype})

    ok_list = []
    fail_list = []
    unreachable_list = []

    def _test_one(entry):
        ok, err = _verify_host(entry["ip"], entry["htype"], svc_name, key_file, rsa_file, cfg=cfg)
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


def _init_check(cfg, json_output=False):
    """Validate init state — local files + remote host SSH."""
    if not json_output:
        fmt.header("Init Check")
        fmt.blank()

    svc_name = cfg.ssh_service_account
    passes = fails = warns = 0
    check_results = []

    def _chk(label, status):
        nonlocal passes, fails, warns
        check_results.append({"check": label, "status": status})
        if status == "pass":
            if not json_output:
                fmt.step_ok(label)
            passes += 1
        elif status == "fail":
            if not json_output:
                fmt.step_fail(label)
            fails += 1
        else:
            if not json_output:
                fmt.step_warn(label)
            warns += 1

    # ── Local checks ──
    if not json_output:
        fmt.line(f"  {fmt.C.BOLD}Local State{fmt.C.RESET}")
        fmt.blank()

    marker = os.path.join(cfg.conf_dir, ".initialized")
    web_only = False
    if os.path.isfile(marker):
        with open(marker) as f:
            marker_content = f.read().strip()
        web_only = "web setup" in marker_content.lower()
        _chk(f"Initialized: {marker_content}", "pass")
    else:
        _chk("Not initialized (.initialized file missing)", "warn")

    # Service account and SSH keys are required for full init but not for
    # web-only setup (dashboard works without fleet SSH access)
    fleet_severity = "warn" if web_only else "fail"

    rc, _, _ = _run(["id", svc_name])
    _chk(f"Service account '{svc_name}' exists", "pass" if rc == 0 else fleet_severity)

    key_file = os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = os.path.join(cfg.key_dir, "freq_id_rsa")
    fleet_key = os.path.expanduser("~/.ssh/fleet_key")
    # Check for SSH key: init-generated OR fleet_key OR key_dir exists but is secure (700)
    has_ssh_key = os.path.isfile(key_file) or os.path.isfile(fleet_key)
    key_dir_secure = os.path.isdir(cfg.key_dir) and not os.access(cfg.key_dir, os.R_OK)
    # Use resolved key (what ssh.run actually uses)
    resolved_key = cfg.ssh_key_path
    has_any_key = has_ssh_key or key_dir_secure or (resolved_key and os.path.isfile(resolved_key))
    _chk("SSH key available", "pass" if has_any_key else fleet_severity)
    _chk("SSH RSA key (iDRAC + switch)", "pass" if os.path.isfile(rsa_file) or key_dir_secure else "warn")

    # Vault may be in a 700 directory (service-account only) — check parent dir
    vault_dir = os.path.dirname(cfg.vault_file)
    if os.path.isfile(cfg.vault_file):
        _chk("Vault file exists", "pass")
    elif os.path.isdir(vault_dir) and not os.access(vault_dir, os.R_OK):
        # Can't read vault dir (700 owned by service account) — that's correct security
        _chk(f"Vault directory secure ({svc_name} only)", "pass")
    else:
        _chk("Vault file exists", "fail")

    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    _chk("freq.toml exists", "pass" if os.path.isfile(toml_path) else "fail")

    if cfg.hosts:
        _chk(f"hosts.toml: {len(cfg.hosts)} hosts", "pass")
    else:
        _chk("hosts.toml is empty", "warn")

    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    _chk("roles.conf exists", "pass" if os.path.isfile(roles_file) else "warn")

    # ── Duplicate host detection ──
    if cfg.hosts:
        seen_ips = {}
        seen_labels = {}
        for h in cfg.hosts:
            if h.ip in seen_ips:
                _chk(f"Duplicate IP: {h.ip} ({h.label} + {seen_ips[h.ip]})", "fail")
            else:
                seen_ips[h.ip] = h.label
            if h.label in seen_labels:
                _chk(f"Duplicate label: {h.label} ({h.ip} + {seen_labels[h.label]})", "fail")
            else:
                seen_labels[h.label] = h.ip

    # ── Remote fleet verification ──
    if cfg.hosts or cfg.pve_nodes:
        if not json_output:
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

    # ── Deep deployment state checks (on reachable hosts) ──
    if cfg.hosts and ok_list:
        import concurrent.futures as _cf

        if not json_output:
            fmt.blank()
            fmt.line(f"  {fmt.C.BOLD}Deployment State{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Verifying service account + agent on reachable hosts...{fmt.C.RESET}")
            fmt.blank()

        key_file = cfg.ssh_key_path

        def _deep_check(entry):
            ip, htype, label = entry["ip"], entry["htype"], entry["label"]
            if htype in ("linux", "pve", "docker", "truenas"):
                cmd = (
                    f"id {svc_name} >/dev/null 2>&1 && "
                    f"sudo -n true 2>/dev/null && "
                    f"test -f /home/{svc_name}/.ssh/authorized_keys && "
                    f"echo DEEP_CHECK_OK"
                )
                use_key = key_file
            elif htype == "pfsense":
                cmd = (
                    f"pw usershow {svc_name} >/dev/null 2>&1 && "
                    f"test -f /home/{svc_name}/.ssh/authorized_keys && "
                    f"echo DEEP_CHECK_OK"
                )
                use_key = key_file
            else:
                return label, ip, htype, True, ""  # iDRAC/switch — SSH verify is sufficient

            ssh_cmd = [
                "ssh", "-n", "-i", use_key,
                "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{svc_name}@{ip}", cmd,
            ]
            rc, out, err = _run(ssh_cmd, timeout=15)
            ok = "DEEP_CHECK_OK" in out
            return label, ip, htype, ok, err.strip()[:80] if not ok else ""

        with _cf.ThreadPoolExecutor(max_workers=10) as pool:
            futs = [pool.submit(_deep_check, h) for h in ok_list]
            for f in _cf.as_completed(futs):
                label, ip, htype, deep_ok, deep_err = f.result()
                if deep_ok:
                    _chk(f"{label}: account + sudo + key verified", "pass")
                else:
                    detail = deep_err or "account/sudo/key missing"
                    _chk(f"{label}: {detail}", "fail")

    if json_output:
        import json as _json

        print(_json.dumps({
            "checks": check_results,
            "passed": passes, "failed": fails, "warnings": warns,
            "total": passes + fails + warns,
        }, indent=2))
        return 1 if fails else 0

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
    """Scan fleet, find broken hosts, redeploy service account.

    Uses bootstrap auth (password or existing key) to reach hosts where
    service account is broken/missing, then deploys using the same machinery
    as the full init wizard.
    """
    fmt.header("Init Fix — Repair Broken Hosts")
    fmt.blank()

    svc_name = cfg.ssh_service_account
    # Use resolved key path (may be fleet_key or ~/.ssh/)
    key_file = cfg.ssh_key_path or os.path.join(cfg.key_dir, "freq_id_ed25519")
    rsa_file = cfg.ssh_rsa_key_path if hasattr(cfg, "ssh_rsa_key_path") else os.path.join(cfg.key_dir, "freq_id_rsa")

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
        "svc_pass": secrets.token_urlsafe(24),  # Auto-generate for --fix mode
        "key_path": key_file,
        "pubkey": pubkey,
        "rsa_key_path": rsa_file,
        "rsa_pubkey": rsa_pubkey,
    }

    if not ctx["pubkey"]:
        fmt.step_fail("FREQ ed25519 public key not found")
        return 1

    # Persist the generated password in vault so it's recoverable
    from freq.modules.vault import vault_set, vault_init

    if not os.path.exists(cfg.vault_file):
        vault_init(cfg)
    vault_key = f"{svc_name}-pass"
    if vault_set(cfg, "DEFAULT", vault_key, ctx["svc_pass"]):
        fmt.step_ok(f"Password stored in vault (key: {vault_key})")
    else:
        fmt.step_warn("Could not store password in vault — deploy will continue")

    # Phase 1: Scan
    fmt.line(f"  {fmt.C.BOLD}Phase 1: Scanning fleet...{fmt.C.RESET}")
    fmt.blank()

    ok_list, fail_list, unreachable_list = _scan_fleet(cfg)

    fmt.line(
        f"  {fmt.C.GREEN}{len(ok_list)} OK{fmt.C.RESET}, "
        f"{fmt.C.RED}{len(fail_list)} broken{fmt.C.RESET}, "
        f"{fmt.C.YELLOW}{len(unreachable_list)} unreachable{fmt.C.RESET}"
    )
    fmt.blank()

    # Include unreachable hosts as candidates — they may need fresh deployment
    if unreachable_list:
        fmt.line(f"  {fmt.C.BOLD}Unreachable hosts (will attempt deployment):{fmt.C.RESET}")
        for h in unreachable_list:
            err_short = h["error"][:60] if h["error"] else "no response"
            fmt.line(f"    {fmt.C.YELLOW}?{fmt.C.RESET} {h['label']} ({h['ip']}) [{h['htype']}] — {err_short}")
        fmt.blank()
        fail_list.extend(unreachable_list)

    if not fail_list:
        fmt.step_ok("All reachable hosts are healthy — nothing to fix")
        fmt.blank()
        fmt.footer()
        return 0

    # Show broken hosts
    fmt.line(f"  {fmt.C.BOLD}Hosts to fix:{fmt.C.RESET}")
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
                ok, _ = _verify_host(h["ip"], h["htype"], svc_name, key_file, rsa_file, cfg=cfg)
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
                        dev_pass = getpass.getpass(
                            f"{fmt.C.PURPLE}{fmt.B_V()}{fmt.C.RESET}  Password for device admin ({dev_user}): "
                        )

            for h in device_broken:
                fmt.blank()
                fmt.line(f"  {fmt.C.BOLD}{h['label']}{fmt.C.RESET} ({h['ip']}) [{h['htype']}]")
                if _deploy_to_host_dispatch(h["ip"], h["htype"], ctx, dev_pass, "", dev_user):
                    ok, _ = _verify_host(h["ip"], h["htype"], svc_name, key_file, rsa_file, cfg=cfg)
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
    fmt.line(
        f"  {fmt.C.BOLD}Results:{fmt.C.RESET} "
        f"{fmt.C.GREEN}{fixed} fixed{fmt.C.RESET}, "
        f"{fmt.C.RED}{failed} failed{fmt.C.RESET}"
    )

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
    fmt.line(
        f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will remove the FREQ service account from ALL hosts.{fmt.C.RESET}"
    )
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
            # Try bootstrap key fallback
            fallback_key = ""
            bootstrap_candidates = [
                os.path.expanduser("~/.ssh/fleet_key"),
                os.path.expanduser("~/.ssh/id_ed25519"),
                os.path.expanduser("~/.ssh/id_rsa"),
            ]
            for candidate in bootstrap_candidates:
                if os.path.isfile(candidate):
                    fallback_key = candidate
                    break
            if fallback_key:
                fmt.step_warn(f"No FREQ SSH keys — using fallback: {fallback_key}")
                ed_key = fallback_key
                has_ed_key = True
            else:
                fmt.step_warn("No FREQ SSH keys found — cannot reach remote hosts")
                fmt.blank()
                fmt.line(f"  {fmt.C.YELLOW}Remote cleanup must be done manually on each host:{fmt.C.RESET}")
                fmt.line(f"  {fmt.C.DIM}  sudo userdel -r {svc_name}{fmt.C.RESET}")
                fmt.line(f"  {fmt.C.DIM}  sudo rm -f /etc/sudoers.d/freq-{svc_name}{fmt.C.RESET}")
                fmt.blank()
                fmt.line(f"  {fmt.C.DIM}Affected hosts ({len(targets)}):{fmt.C.RESET}")
                for ip, htype, label in targets:
                    fmt.line(f"    {fmt.C.DIM}{label}{fmt.C.RESET}")
                fmt.blank()
                skip = len(targets)

        if has_ed_key or has_rsa_key:
            for ip, htype, label in targets:
                fmt.line(f"  {fmt.C.BOLD}{label}{fmt.C.RESET} [{htype}]")

                success, err_info = _remove_from_host_dispatch(
                    ip,
                    htype,
                    svc_name,
                    ed_key,
                    rsa_key,
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
        fmt.line(
            f"  Remote: {fmt.C.GREEN}{ok} removed{fmt.C.RESET}, "
            f"{fmt.C.RED}{fail} failed{fmt.C.RESET}, "
            f"{fmt.C.YELLOW}{skip} skipped{fmt.C.RESET}"
        )

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
                steps.append(
                    f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): userdel + sudoers + key [{h.htype}]"
                )
            elif h.htype == "pfsense":
                steps.append(
                    f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): SSH key only (pfSense — manual account removal)"
                )
            elif h.htype == "idrac":
                steps.append(
                    f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): disable slot + clear RSA key [iDRAC]"
                )
            elif h.htype == "switch":
                steps.append(
                    f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): no username + clear pubkey-chain [switch]"
                )
            else:
                steps.append(f"{step_n}. Remove '{svc_name}' from {h.label} ({h.ip}): [{h.htype}]")
            step_n += 1

    # Local cleanup
    steps.extend(
        [
            f"{step_n}. Remove local sudoers: /etc/sudoers.d/freq-{svc_name}",
            f"{step_n + 1}. Delete SSH keys: {cfg.key_dir}/freq_id_ed25519, freq_id_rsa (+ .pub)",
            f"{step_n + 2}. Delete vault: {cfg.vault_file}",
            f"{step_n + 3}. Delete roles: {cfg.conf_dir}/roles.conf",
            f"{step_n + 4}. Delete init marker: {cfg.conf_dir}/.initialized",
            f"{step_n + 5}. Delete local account '{svc_name}' + home directory",
        ]
    )

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
    fmt.header("Init — Dry Run (13 Phases)")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}This shows what 'freq init' would do without making changes:{fmt.C.RESET}")
    fmt.blank()

    phases = [
        ("Phase 1", "Prerequisites", "Check binaries (ssh, openssl), create dirs, seed configs"),
        ("Phase 2", "Cluster Config + VLAN Discovery", "PVE nodes, gateway, bootstrap auth, discover VLANs from PVE"),
        ("Phase 3", "Service Account", f"Create '{cfg.ssh_service_account}' with NOPASSWD sudo, init vault"),
        ("Phase 4", "SSH Keys", f"Generate ed25519 + RSA-4096 keypairs in {cfg.key_dir}/"),
        ("Phase 5", "PVE Node Deployment", f"Deploy {cfg.ssh_service_account} to {len(cfg.pve_nodes) if cfg.pve_nodes else 0} PVE node(s)"),
        ("Phase 6", "PVE API Token", "Create freq-ops@pam!freq-rw token, save to /etc/freq/credentials/"),
        ("Phase 7", "Fleet Discovery", "PVE API + multi-VLAN sweep, detect infrastructure, write hosts.toml + fleet-boundaries"),
        ("Phase 8", "Fleet Deployment", f"Deploy {cfg.ssh_service_account} to all discovered hosts (Linux, pfSense, iDRAC, switch)"),
        ("Phase 9", "Fleet Configuration", "Docker host tagging, metrics agent deploy, VM categorization"),
        ("Phase 10", "PDM Setup", "Optional Proxmox Datacenter Manager integration"),
        ("Phase 11", "Admin Accounts", "Configure RBAC roles (admin for current user + service account)"),
        ("Phase 12", "Verification", "SSH/sudo all hosts, PVE API, agent health, dashboard readiness"),
        ("Phase 13", "Summary", "Fleet topology, infrastructure IPs, component ports, next steps"),
    ]

    for num, name, desc in phases:
        fmt.line(f"    {fmt.C.BOLD}{num}{fmt.C.RESET}: {name}")
        fmt.line(f"      {fmt.C.DIM}{desc}{fmt.C.RESET}")

    if cfg.pve_nodes:
        fmt.blank()
        fmt.line(f"  PVE nodes: {', '.join(cfg.pve_nodes)}")
    if cfg.hosts:
        fmt.line(f"  Fleet hosts: {len(cfg.hosts)} registered")

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
            lines.append(f'\n[{section}]\n{key} = "{value}"\n')

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

    # Auto-detect bootstrap key only when NO password was provided.
    # If --bootstrap-password-file is given, honor password-first — don't
    # silently switch to key auth just because a local key happens to exist.
    if not bootstrap_key and not bootstrap_pass:
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
    if len(svc_pass) < 8:
        fmt.line(f"  {fmt.C.RED}Password too short (min 8 chars){fmt.C.RESET}")
        return 1

    ctx = {
        "svc_name": cfg.ssh_service_account,
        "svc_pass": svc_pass,
        "key_path": "",
        "pubkey": "",
        "rsa_key_path": "",
        "rsa_pubkey": "",
        "bootstrap_key": bootstrap_key or "",
        "bootstrap_pass": bootstrap_pass,
        "bootstrap_user": bootstrap_user,
        "dry_run": False,
    }

    fmt.header("Init — Headless Mode")
    fmt.blank()
    if bootstrap_key:
        fmt.line(
            f"  Bootstrap: {fmt.C.CYAN}{bootstrap_user}{fmt.C.RESET} via key {fmt.C.CYAN}{bootstrap_key}{fmt.C.RESET}"
        )
    else:
        fmt.line(f"  Bootstrap: {fmt.C.CYAN}{bootstrap_user}{fmt.C.RESET} via password (sshpass)")
    fmt.line(f"  Service account: {fmt.C.CYAN}{ctx['svc_name']}{fmt.C.RESET}")
    fmt.blank()

    headless_total = 12

    # ── Phase 1: Prerequisites ──
    _phase(1, headless_total, "Prerequisites")
    if not _phase_welcome(cfg):
        return 1

    # ── Phase 2: Cluster Configuration + VLAN Discovery ──
    _phase(2, headless_total, "Cluster Configuration + VLAN Discovery")
    _phase_configure(cfg, args)
    _discover_vlans_from_pve(cfg, ctx)

    # ── Phase 3: Local Service Account ──
    _phase(3, headless_total, "Local Service Account")
    if not _headless_local_account(cfg, ctx):
        return 1

    # ── Phase 4: SSH Keys ──
    _phase(4, headless_total, "SSH Key Generation")
    _phase_ssh_keys(cfg, ctx)

    # ── Phase 5: PVE Node Deployment ──
    _phase(5, headless_total, "PVE Node Deployment")
    _headless_fleet_deploy(
        cfg,
        ctx,
        bootstrap_key,
        bootstrap_user,
        bootstrap_pass=bootstrap_pass,
        device_password_file=None,
        device_user="root",
        device_creds={},
        pve_only=True,
    )

    # ── Phase 6: PVE API Token ──
    _phase(6, headless_total, "PVE API Token")
    _phase_pve_api_token(cfg, ctx)

    # ── Phase 7: Fleet Discovery ──
    _phase(7, headless_total, "Fleet Discovery")
    _phase_fleet_discover(cfg, ctx, args)

    # ── Phase 8: Fleet Deployment ──
    _phase(8, headless_total, "Fleet Deployment")

    # Import hosts from --hosts-file if provided
    hosts_file_arg = getattr(args, "hosts_file", None)
    if hosts_file_arg and os.path.isfile(hosts_file_arg):
        fmt.step_start(f"Importing fleet hosts from {hosts_file_arg}")
        shutil.copy2(hosts_file_arg, cfg.hosts_file)
        from freq.core.config import load_hosts, load_hosts_toml

        try:
            if hosts_file_arg.endswith(".toml"):
                cfg.hosts = load_hosts_toml(cfg.hosts_file)
            else:
                cfg.hosts = load_hosts(cfg.hosts_file)
            fmt.step_ok(f"Imported {len(cfg.hosts)} host(s) from {hosts_file_arg}")
        except Exception as e:
            fmt.step_fail(f"Failed to reload hosts: {e}")

    # Load per-device credentials
    device_creds = _load_device_credentials(device_credentials_file)
    if device_creds:
        fmt.step_ok(f"Per-device credentials loaded: {', '.join(sorted(device_creds.keys()))}")
    elif device_password_file:
        fmt.step_warn("Using deprecated --device-password-file (migrate to --device-credentials)")

    _headless_fleet_deploy(
        cfg,
        ctx,
        bootstrap_key,
        bootstrap_user,
        bootstrap_pass=bootstrap_pass,
        device_password_file=device_password_file,
        device_user=device_user,
        device_creds=device_creds,
    )

    # ── Phase 9: Fleet Configuration ──
    _phase(9, headless_total, "Fleet Configuration")
    _phase_fleet_configure(cfg, ctx)

    # ── Phase 10: PDM Setup ──
    _phase(10, headless_total, "PDM Setup")
    _phase_pdm(cfg, ctx, args)

    # ── Phase 11: RBAC ──
    _phase(11, headless_total, "RBAC Setup")
    roles_file = os.path.join(cfg.conf_dir, "roles.conf")
    existing_lines = []
    if os.path.isfile(roles_file):
        with open(roles_file) as f:
            existing_lines = f.readlines()
    # Only check uncommented lines — template comments like '# freq-admin:admin'
    # must not fool the presence check
    active_roles = [l.strip() for l in existing_lines if l.strip() and not l.strip().startswith("#")]
    with open(roles_file, "a") as f:
        if not any(l.startswith(f"{bootstrap_user}:") for l in active_roles):
            f.write(f"{bootstrap_user}:admin\n")
            fmt.step_ok(f"Added {bootstrap_user} as admin")
        else:
            fmt.step_ok(f"{bootstrap_user} already in roles")
        svc_name = ctx["svc_name"]
        if not any(l.startswith(f"{svc_name}:") for l in active_roles):
            f.write(f"{svc_name}:admin\n")
            fmt.step_ok(f"Added {svc_name} as admin")
        else:
            fmt.step_ok(f"{svc_name} already in roles")

    # Seed dashboard password for bootstrap user (the human operator).
    # The service account (freq-admin) does NOT get a web login — it runs
    # the dashboard process but doesn't authenticate to it. Only the
    # bootstrap user (freq-ops) should be able to log in.
    try:
        from freq.modules.vault import vault_init, vault_set
        from freq.api.auth import hash_password
        if not os.path.exists(cfg.vault_file):
            vault_init(cfg)
        boot_pass = ctx.get("bootstrap_pass", "")
        svc_pass = ctx.get("svc_pass", "")
        if bootstrap_user:
            # Use bootstrap password when available, fall back to svc_pass for key-based bootstrap
            user_pass = boot_pass or svc_pass
            if user_pass:
                vault_set(cfg, "auth", f"password_{bootstrap_user}", hash_password(user_pass))
                fmt.step_ok(f"Dashboard password set for {bootstrap_user}")
    except Exception as e:
        fmt.step_warn(f"Could not set dashboard password: {e}")

    # ── Post-init permissions ──
    # Config files must not be world-writable (init runs as root, umask may be 000)
    if cfg.conf_dir and os.path.exists(cfg.conf_dir):
        try:
            subprocess.run(["chmod", "755", cfg.conf_dir], capture_output=True, timeout=5)
            for f in os.listdir(cfg.conf_dir):
                fpath = os.path.join(cfg.conf_dir, f)
                if os.path.isfile(fpath):
                    os.chmod(fpath, 0o644)
                elif os.path.isdir(fpath):
                    os.chmod(fpath, 0o755)
            fmt.step_ok("Config file permissions hardened (644)")
        except Exception:
            pass
    # data/ subdirs: log/cache 755, keys/vault 700
    for d in [cfg.log_dir, os.path.join(cfg.data_dir, "cache")]:
        d_path = d if os.path.isdir(d) else os.path.dirname(d)
        if d_path and os.path.exists(d_path):
            try:
                subprocess.run(["chmod", "755", d_path], capture_output=True, timeout=5)
            except Exception:
                pass
    for d in [os.path.join(cfg.data_dir, "keys"), os.path.join(cfg.data_dir, "vault")]:
        if os.path.isdir(d):
            try:
                subprocess.run(["chmod", "700", d], capture_output=True, timeout=5)
            except Exception:
                pass

    # ── Phase 12: Verification ──
    _phase(12, headless_total, "Verification")
    verified = _phase_verify(cfg, ctx)

    fmt.blank()
    if verified:
        with open(INIT_MARKER, "w") as f:
            f.write(f"{cfg.version}\n")
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
    p = subprocess.Popen(["/usr/sbin/chpasswd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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


def _headless_fleet_deploy(
    cfg,
    ctx,
    bootstrap_key,
    bootstrap_user,
    bootstrap_pass="",
    device_password_file=None,
    device_user="root",
    device_creds=None,
    pve_only=False,
):
    """Deploy service account to PVE + fleet hosts using bootstrap credentials.

    Uses the unified platform dispatcher for all host types.
    Supports bootstrap via SSH key (--bootstrap-key) or password (--bootstrap-password-file).

    pve_only: if True, only deploy to PVE nodes (Phase 5). Fleet hosts
    are deployed later in Phase 8 after discovery populates hosts.toml.

    device_creds: dict from _load_device_credentials() — per-device-type auth:
        {"pfsense": {"user": "root", "password": "..."}, "switch": {"user": "gigecolo", "password": "..."}}
    Falls back to legacy device_password_file + device_user if device_creds not provided.
    """
    if device_creds is None:
        device_creds = {}
    # Collect targets: PVE nodes first, then fleet hosts (deduplicated by IP)
    seen_ips = set()
    targets = []

    for i, ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else ip
        targets.append({"ip": ip, "label": name, "htype": "pve"})
        seen_ips.add(ip)

    if not pve_only:
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
            if device_pass:
                auth_pass = device_pass
                auth_key = ""
                auth_user = device_user
            else:
                fmt.step_warn(f"No device credentials for {htype} — skipping (provide --device-credentials)")
                skip += 1
                continue
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
            # TrueNAS: prefer device_creds, fall back to bootstrap creds only
            # if the user deployed the same key/user to the NAS manually.
            # If neither works, the connectivity check below produces a
            # truthful 'auth failed' message.
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
                    "ssh",
                    "-n",
                    "-i",
                    bootstrap_key,
                    "-o",
                    "ConnectTimeout=5",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    f"{bootstrap_user}@{ip}",
                    "echo OK",
                ]
            else:
                # Password-based connectivity check via sshpass (tempfile, not CLI arg)
                import tempfile

                _bp_fd, _bp_path = tempfile.mkstemp(prefix="freq-bp-")
                os.write(_bp_fd, bootstrap_pass.encode())
                os.close(_bp_fd)
                ssh_check = [
                    "sshpass",
                    "-f",
                    _bp_path,
                    "ssh",
                    "-n",
                    "-o",
                    "ConnectTimeout=5",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "PubkeyAuthentication=no",
                    f"{bootstrap_user}@{ip}",
                    "echo OK",
                ]
            rc, _, err = _run(ssh_check, timeout=QUICK_CHECK_TIMEOUT)
            # Clean up temp password file if created
            if not bootstrap_key:
                try:
                    os.unlink(_bp_path)
                except OSError:
                    pass
            if rc != 0:
                if _is_skip_error(err) or rc == 5:
                    reason = _skip_reason(err) if err.strip() else _ssh_error_msg(rc, err)
                    # TrueNAS uses its own root account — add specific hint
                    if htype == "truenas" and "auth failed" in reason:
                        reason = "auth failed (add [truenas] to --device-credentials with root user)"
                    fmt.step_warn(f"{label} ({ip}) — {reason} (skipped)")
                    skip += 1
                else:
                    fmt.step_fail(f"Cannot connect ({_ssh_error_msg(rc, err)})")
                    fail += 1
                continue

        if _deploy_to_host_dispatch(ip, htype, ctx, auth_pass, auth_key, auth_user):
            ok += 1
        else:
            fail += 1

    # Persist device password for ongoing iDRAC/switch SSH access
    has_devices = any(t["htype"] in ("idrac", "switch") for t in targets)
    if has_devices and ok > 0:
        device_passwords = {
            device_creds[t["htype"]]["password"]
            for t in targets
            if t["htype"] in ("idrac", "switch") and t["htype"] in device_creds
        }
        if device_passwords and len(device_passwords) == 1:
            _persist_legacy_password_file(cfg, ctx.get("svc_name", cfg.ssh_service_account if hasattr(cfg, "ssh_service_account") else "freq-admin"), next(iter(device_passwords)))
        elif len(device_passwords) > 1:
            fmt.step_warn("Multiple distinct iDRAC/switch passwords used — legacy password fallback not persisted")

    fmt.blank()
    fmt.line(
        f"  Fleet: {fmt.C.GREEN}{ok} OK{fmt.C.RESET}, "
        f"{fmt.C.RED}{fail} failed{fmt.C.RESET}, "
        f"{fmt.C.YELLOW}{skip} skipped{fmt.C.RESET}"
    )
