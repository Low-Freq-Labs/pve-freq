"""FREQ Doctor — 17-point self-diagnostic.

Domain: freq doctor

Checks everything FREQ needs to run: Python version, platform, paths,
config, SSH key, fleet connectivity (parallel SSH), fleet data integrity,
PVE cluster reachability, prerequisites, personality pack, VLANs, distros.
Returns 0 if healthy, 1 if any critical check fails. Warnings don't fail.

Replaces: Manual troubleshooting checklists, ad-hoc SSH connectivity tests

Architecture:
    - Each check is a function returning (ok, message) or (ok, message, extra)
    - Uses freq/core/preflight.py for Python/platform/binary checks
    - Uses freq/core/ssh.py for fleet connectivity probes
    - Output through freq/core/fmt.py for consistent branding

Design decisions:
    - 17 checks, not 5. Thoroughness > speed for diagnostics.
    - Fleet SSH is tested in parallel (ThreadPoolExecutor) — 14 hosts in <3s.
    - Non-fatal warnings (missing personality pack) don't return exit code 1.
"""

import os
import shutil
import subprocess
import time

from freq.core.config import FreqConfig
from freq.core import fmt
from freq.core.ssh import run as ssh_run

# Doctor check timeouts
DOCTOR_CMD_TIMEOUT = 5
DOCTOR_PVE_TIMEOUT = 10


def run(cfg: FreqConfig, json_output: bool = False) -> int:
    """Run all diagnostic checks. Returns 0 if all pass, 1 if any fail."""
    start = time.monotonic()
    check_results = []

    if not json_output:
        fmt.header("Doctor", "PVE FREQ")
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Self-Diagnostic{fmt.C.RESET}")
        fmt.blank()

    passed = 0
    failed = 0
    warnings = 0

    sections = [
        (
            "System",
            [
                _check_python,
                _check_platform,
                _check_prerequisites,
            ],
        ),
        (
            "Installation",
            [
                _check_install_dir,
                _check_config,
                _check_data_dirs,
                _check_personality,
            ],
        ),
        (
            "SSH & Connectivity",
            [
                _check_ssh_binary,
                _check_ssh_key,
                _check_fleet_connectivity,
                _check_service_account,
                _check_legacy_passwords,
            ],
        ),
        (
            "Fleet Data",
            [
                _check_hosts,
                _check_hosts_validity,
                _check_vlans,
                _check_distros,
            ],
        ),
        (
            "PVE Cluster",
            [
                _check_pve_nodes,
            ],
        ),
    ]

    import io, sys
    for section_name, checks in sections:
        if not json_output:
            fmt.line(f"  {fmt.C.PURPLE_BOLD}{section_name}{fmt.C.RESET}")
        for check in checks:
            # In JSON mode, suppress check functions' terminal output
            if json_output:
                _old_stdout = sys.stdout
                sys.stdout = io.StringIO()
            try:
                result = check(cfg)
            finally:
                if json_output:
                    sys.stdout = _old_stdout
            status = "pass" if result == 0 else "fail" if result == 1 else "warn"
            check_results.append({"section": section_name, "name": check.__name__.lstrip("_"), "status": status})
            if result == 0:
                passed += 1
            elif result == 1:
                failed += 1
            else:
                warnings += 1
        if not json_output:
            print()

    duration = time.monotonic() - start

    # Save health history to SQLite
    from freq.core.log import save_health
    save_health(passed, failed, warnings, duration, check_results)

    if json_output:
        import json as _json

        total = passed + failed + warnings
        status = "healthy" if failed == 0 and warnings == 0 else "degraded" if failed == 0 else "unhealthy"
        result = {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "total": total,
            "status": status,
            "duration": round(duration, 2),
            "checks": check_results,
        }
        print(_json.dumps(result, indent=2))
        return 1 if failed > 0 else 0

    fmt.divider("Summary")
    fmt.blank()

    total = passed + failed + warnings
    fmt.line(
        f"  {fmt.C.GREEN}{passed}{fmt.C.RESET} passed  "
        f"{fmt.C.YELLOW}{warnings}{fmt.C.RESET} warnings  "
        f"{fmt.C.RED}{failed}{fmt.C.RESET} failed  "
        f"({total} total)"
    )
    fmt.blank()

    if failed == 0 and warnings == 0:
        fmt.line(f"{fmt.C.GREEN}FREQ is healthy. All systems nominal.{fmt.C.RESET}")
    elif failed == 0:
        fmt.line(f"{fmt.C.YELLOW}FREQ is operational with warnings.{fmt.C.RESET}")
    else:
        fmt.line(f"{fmt.C.RED}FREQ has issues that need attention.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()

    return 1 if failed > 0 else 0


def show_history(cfg: FreqConfig) -> int:
    """Display health check history from SQLite."""
    from freq.core.log import read_health

    entries = read_health(last=20)

    if not entries:
        fmt.line("No health history found. Run 'freq doctor' to start recording.")
        return 0

    fmt.header("Doctor History")
    fmt.blank()
    fmt.line(f"  {'Timestamp':<28} {'Pass':>6} {'Warn':>6} {'Fail':>6} {'Duration':>10}")
    fmt.line(f"  {'─' * 28} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 10}")

    for e in entries:
        ts = e.get("ts", "?")[:19].replace("T", " ")
        p = e.get("passed", 0)
        w = e.get("warnings", 0)
        f_count = e.get("failed", 0)
        dur = f"{e.get('duration', 0):.1f}s"

        status_color = fmt.C.GREEN if f_count == 0 and w == 0 else fmt.C.YELLOW if f_count == 0 else fmt.C.RED
        fmt.line(f"  {ts:<28} {status_color}{p:>6}{fmt.C.RESET} {w:>6} {f_count:>6} {dur:>10}")

    fmt.blank()
    fmt.line(f"  {len(entries)} total entries")
    fmt.blank()
    return 0


# --- System ---


def _check_python(cfg: FreqConfig) -> int:
    from freq.core.preflight import check_python_version

    ok, msg = check_python_version()
    if ok:
        fmt.step_ok(msg)
        return 0
    else:
        fmt.step_fail(msg)
        return 1


def _check_platform(cfg: FreqConfig) -> int:
    from freq.core.preflight import check_platform

    ok, msg, _info = check_platform()
    if ok:
        fmt.step_ok(msg)
        return 0
    else:
        fmt.step_warn(msg)
        return 2


def _check_prerequisites(cfg: FreqConfig) -> int:
    """Check required and optional system tools."""
    from freq.core.preflight import check_required_binaries, check_optional_binaries

    ok_req, msg_req, _ = check_required_binaries()
    if not ok_req:
        fmt.step_fail(msg_req)
        return 1

    ok_opt, msg_opt, _ = check_optional_binaries()
    if not ok_opt:
        fmt.step_warn(msg_opt)
        return 2

    fmt.step_ok("Prerequisites: all found")
    return 0


# --- Installation ---


def _check_install_dir(cfg: FreqConfig) -> int:
    if os.path.isdir(cfg.install_dir):
        fmt.step_ok(f"Install dir: {cfg.install_dir}")
        return 0
    else:
        fmt.step_fail(f"Install dir missing: {cfg.install_dir}")
        return 1


def _check_config(cfg: FreqConfig) -> int:
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    if os.path.isfile(toml_path):
        fmt.step_ok("Config: freq.toml loaded")
        return 0
    else:
        fmt.step_warn("Config: freq.toml not found (running on defaults)")
        return 2


def _check_data_dirs(cfg: FreqConfig) -> int:
    # Secure dirs are intentionally 700 owned by the service account.
    # Operator can't write to them — that's correct, not a defect.
    secure_dir_names = {"data/vault", "data/keys"}
    dirs = [
        ("data", cfg.data_dir),
        ("data/log", os.path.dirname(cfg.log_file)),
        ("data/vault", cfg.vault_dir),
        ("data/keys", cfg.key_dir),
    ]
    all_ok = True
    import getpass
    current_user = getpass.getuser()
    is_service_account = current_user == cfg.ssh_service_account

    for name, path in dirs:
        if os.path.isdir(path):
            if not os.access(path, os.W_OK):
                if name in secure_dir_names and not is_service_account:
                    pass  # Expected: secure dirs not writable by operators
                elif name == "data/log" and not is_service_account:
                    pass  # Operator doesn't write logs; service account does
                else:
                    fmt.step_warn(f"Dir not writable: {name}")
                    all_ok = False
        else:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                fmt.step_fail(f"Cannot create: {name}")
                return 1

    # Check if logs are going to expected path or diverted to fallback
    # This is expected behavior for operators — they log to ~/.freq/log/
    # Only flag as a warning when the service account's logs are diverted
    from freq.core.log import _LOG_FILE
    expected_log_dir = os.path.dirname(cfg.log_file)
    if _LOG_FILE and not _LOG_FILE.startswith(expected_log_dir):
        if is_service_account:
            fmt.step_warn(f"Logs diverted to {_LOG_FILE} (expected {expected_log_dir})")
            all_ok = False
        # Operator log diversion to ~/.freq/log/ is normal — not flagged

    if all_ok:
        fmt.step_ok("Data directories")
    return 0 if all_ok else 2


def _check_personality(cfg: FreqConfig) -> int:
    pack_path = os.path.join(cfg.conf_dir, "personality", f"{cfg.build}.toml")
    if os.path.isfile(pack_path):
        fmt.step_ok(f"Personality: {cfg.build} pack")
        return 0
    elif cfg.build == "default":
        # Built-in default pack is always available — no file needed
        fmt.step_ok("Personality: built-in default")
        return 0
    else:
        fmt.step_warn(f"Personality: {cfg.build} pack not found")
        return 2


# --- SSH & Connectivity ---


def _check_ssh_binary(cfg: FreqConfig) -> int:
    if shutil.which("ssh"):
        try:
            result = subprocess.run(["ssh", "-V"], capture_output=True, text=True, timeout=DOCTOR_CMD_TIMEOUT)
            ver = (result.stderr or result.stdout).strip()
            fmt.step_ok(f"SSH: {ver.split(',')[0] if ver else 'available'}")
            return 0
        except (subprocess.TimeoutExpired, OSError):
            fmt.step_ok("SSH: available")
            return 0
    else:
        fmt.step_fail("SSH: not found")
        return 1


def _check_ssh_key(cfg: FreqConfig) -> int:
    if cfg.ssh_key_path and os.path.isfile(cfg.ssh_key_path):
        key_file = os.path.basename(cfg.ssh_key_path)
        # Check permissions
        mode = oct(os.stat(cfg.ssh_key_path).st_mode)[-3:]
        if mode not in ("600", "400"):
            fmt.step_warn(f"SSH key: {key_file} (permissions {mode}, should be 600)")
            return 2
        # Check readability — key might have correct perms but be owned by another user
        if not os.access(cfg.ssh_key_path, os.R_OK):
            key_owner = _get_file_owner(cfg.ssh_key_path)
            fmt.step_warn(f"SSH key: {key_file} ({mode}) — not readable by current user (owned by {key_owner})")
            return 2
        fmt.step_ok(f"SSH key: {key_file} ({mode})")
        return 0
    else:
        fmt.step_warn("SSH key: not found (fleet operations will fail)")
        return 2


def _get_file_owner(path: str) -> str:
    """Get file owner name, fallback to UID."""
    try:
        import pwd
        st = os.stat(path)
        return pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, OSError):
        try:
            return str(os.stat(path).st_uid)
        except OSError:
            return "unknown"


def _check_fleet_connectivity(cfg: FreqConfig) -> int:
    """Test SSH connectivity to ALL fleet hosts in parallel with device-appropriate commands."""
    if not cfg.hosts:
        fmt.step_info("Fleet connectivity: no hosts to test")
        return 0

    import concurrent.futures

    # Device-specific verify commands (same as init Phase 12)
    VERIFY_CMDS = {
        "linux": "sudo -n true",
        "pve": "sudo -n true",
        "docker": "sudo -n true",
        "truenas": "sudo -n true",
        "pfsense": "echo OK",
        "idrac": "racadm getsysinfo -s",
        "switch": "show version | include uptime",
    }

    def _test(h):
        cmd = VERIFY_CMDS.get(h.htype, "echo ok")
        key = cfg.ssh_key_path
        is_legacy = h.htype in ("idrac", "switch")
        if is_legacy:
            key = getattr(cfg, "ssh_rsa_key_path", None) or cfg.ssh_key_path
        # Legacy devices need longer timeouts (sshpass + cipher negotiation)
        ct = 10 if is_legacy else 3
        ct_cmd = 15 if is_legacy else DOCTOR_CMD_TIMEOUT
        r = ssh_run(
            host=h.ip,
            command=cmd,
            key_path=key,
            connect_timeout=ct,
            command_timeout=ct_cmd,
            htype=h.htype,
            use_sudo=False,
            cfg=cfg,
        )
        # Operator-context auth issue: legacy device failed with permission
        # denied. This is not 'down' — it's that the operator doesn't have
        # the service account's RSA key. CLI should reflect this honestly.
        err_l = (r.stderr or "").lower()
        operator_auth = is_legacy and ("permission denied" in err_l or "publickey" in err_l)
        return h, r.returncode == 0, operator_auth

    reachable = 0
    unreachable = []
    na = 0
    total = len(cfg.hosts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        for h, ok, operator_auth in pool.map(lambda h: _test(h), cfg.hosts):
            if ok:
                reachable += 1
            elif operator_auth:
                na += 1  # Don't count as down — operator context mismatch
            else:
                unreachable.append(h.label)

    total_checkable = total - na
    if reachable == total_checkable and total_checkable > 0:
        if na:
            fmt.step_ok(f"Fleet SSH: {reachable}/{total_checkable} reachable ({na} n/a — need svc account)")
        else:
            fmt.step_ok(f"Fleet SSH: {reachable}/{total} hosts reachable")
        return 0
    elif reachable > 0:
        down = ", ".join(unreachable[:5])
        suffix = f" +{len(unreachable)-5} more" if len(unreachable) > 5 else ""
        na_suffix = f" ({na} n/a)" if na else ""
        fmt.step_warn(f"Fleet SSH: {reachable}/{total_checkable} reachable (down: {down}{suffix}){na_suffix}")
        return 2
    else:
        fmt.step_fail(f"Fleet SSH: 0/{total_checkable} reachable")
        return 1


def _check_service_account(cfg: FreqConfig) -> int:
    """Verify service account exists and has correct permissions on reachable hosts."""
    if not cfg.hosts:
        return 0

    import concurrent.futures

    svc = cfg.ssh_service_account
    # Sample: first 2 of each type to keep it fast
    by_type = {}
    for h in cfg.hosts:
        by_type.setdefault(h.htype, []).append(h)
    sample = []
    for hosts in by_type.values():
        sample.extend(hosts[:2])

    if not sample:
        return 0

    def _test(h):
        if h.htype in ("idrac", "switch"):
            return h, True, ""  # SSH verify is sufficient for these
        if h.htype == "pfsense":
            cmd = f"pw usershow {svc} && echo ACCT_OK"
        else:
            cmd = f"id {svc} && sudo -n true && echo ACCT_OK"
        r = ssh_run(
            host=h.ip, command=cmd, key_path=cfg.ssh_key_path,
            connect_timeout=3, command_timeout=DOCTOR_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False, cfg=cfg,
        )
        ok = "ACCT_OK" in (r.stdout or "")
        return h, ok, r.stderr.strip()[:60] if not ok else ""

    issues = []
    unreachable = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        for h, ok, err in pool.map(lambda h: _test(h), sample):
            if not ok and h.htype not in ("idrac", "switch"):
                # Distinguish unreachable (SSH connection failure) from account issues
                if "Permission denied" in err or "Connection refused" in err or "No route" in err or "timed out" in err or "connect to host" in err:
                    unreachable.append(h.label)
                else:
                    issues.append(f"{h.label}: {err or 'account/sudo missing'}")

    verified = len(sample) - len(issues) - len(unreachable)
    if not issues and not unreachable:
        fmt.step_ok(f"Service account '{svc}': verified on {len(sample)} sampled hosts")
        return 0
    elif not issues and unreachable:
        fmt.step_warn(f"Service account '{svc}': {verified} verified, {len(unreachable)} unreachable ({', '.join(unreachable[:3])})")
        return 2
    else:
        fmt.step_fail(f"Service account: {len(issues)} issue(s) — {issues[0]}")
        return 1


def _check_legacy_passwords(cfg: FreqConfig) -> int:
    """Verify password files exist for legacy devices that need them."""
    legacy_hosts = [h for h in cfg.hosts if h.htype in ("idrac", "switch")]
    if not legacy_hosts:
        return 0  # No legacy devices, nothing to check

    pw_file = getattr(cfg, "legacy_password_file", "") or ""
    if pw_file:
        # The file may be inside a service-account-owned dir (e.g. ~/.ssh/ with 700).
        # When an operator runs doctor, os.path.isfile() returns False even though
        # the file exists. Check if the parent dir is a secure service-owned dir.
        if os.path.isfile(pw_file):
            fmt.step_ok(f"Legacy password file: {os.path.basename(pw_file)}")
            return 0
        parent = os.path.dirname(pw_file)
        if os.path.isdir(parent) and not os.access(parent, os.R_OK):
            # Parent exists but is unreadable (likely 700 service-account dir)
            fmt.step_ok(f"Legacy password file: {os.path.basename(pw_file)} (in secure dir)")
            return 0
        fmt.step_warn(f"Legacy password file configured but missing: {pw_file}")
        return 2
    else:
        # No legacy_password_file — this is OK if device-credentials were used
        return 0


# --- Fleet Data ---


def _check_hosts(cfg: FreqConfig) -> int:
    if cfg.hosts:
        from freq.core.resolve import all_types

        types = all_types(cfg.hosts)
        type_str = ", ".join(f"{c} {t}" for t, c in sorted(types.items()))
        fmt.step_ok(f"Fleet: {len(cfg.hosts)} hosts ({type_str})")
        return 0
    elif os.path.isfile(cfg.hosts_file):
        fmt.step_warn("Fleet: hosts.toml exists but is empty")
        return 2
    else:
        fmt.step_warn("Fleet: no hosts.toml (run freq init)")
        return 2


def _check_hosts_validity(cfg: FreqConfig) -> int:
    """Check for duplicate IPs or labels in fleet registry."""
    if not cfg.hosts:
        return 0  # Nothing to validate

    from freq.core import validate

    ips = set()
    labels = set()
    issues = []

    for h in cfg.hosts:
        if not validate.ip(h.ip):
            issues.append(f"invalid IP: {h.ip}")
        if h.ip in ips:
            issues.append(f"duplicate IP: {h.ip}")
        ips.add(h.ip)

        if h.label in labels:
            issues.append(f"duplicate label: {h.label}")
        labels.add(h.label)

    if issues:
        fmt.step_fail(f"Fleet data: {len(issues)} issue(s) — {issues[0]}")
        return 1
    else:
        fmt.step_ok("Fleet data: no duplicates, all IPs valid")
        return 0


def _check_vlans(cfg: FreqConfig) -> int:
    vlan_path = os.path.join(cfg.conf_dir, "vlans.toml")
    if cfg.vlans:
        fmt.step_ok(f"VLANs: {len(cfg.vlans)} defined")
        return 0
    elif os.path.isfile(vlan_path):
        fmt.step_warn("VLANs: vlans.toml exists but no VLANs loaded")
        return 2
    else:
        fmt.step_info("VLANs: no vlans.toml")
        return 0


def _check_distros(cfg: FreqConfig) -> int:
    distro_path = os.path.join(cfg.conf_dir, "distros.toml")
    if cfg.distros:
        fmt.step_ok(f"Distros: {len(cfg.distros)} cloud images defined")
        return 0
    elif os.path.isfile(distro_path):
        fmt.step_warn("Distros: distros.toml exists but no distros loaded")
        return 2
    else:
        fmt.step_info("Distros: no distros.toml")
        return 0


# --- PVE Cluster ---


def _check_pve_nodes(cfg: FreqConfig) -> int:
    if not cfg.pve_nodes:
        fmt.step_info("PVE: no nodes configured")
        return 0

    reachable = 0
    pve_version = ""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip,
            command="sudo pvesh get /version --output-format json 2>/dev/null || echo '{}'",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=DOCTOR_PVE_TIMEOUT,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode == 0 and "version" in r.stdout:
            reachable += 1
            if not pve_version:
                import json

                try:
                    data = json.loads(r.stdout)
                    pve_version = data.get("version", "")
                except json.JSONDecodeError:
                    pass

    # Check minimum PVE version (7.0+ required for cloud-init, QEMU 6.x, etc.)
    MIN_PVE = (7, 0)
    if pve_version:
        try:
            major, minor = (int(x) for x in pve_version.split(".")[:2])
            if (major, minor) < MIN_PVE:
                fmt.step_warn(f"PVE {pve_version} detected — FREQ requires PVE {MIN_PVE[0]}.{MIN_PVE[1]}+")
        except (ValueError, IndexError):
            pass

    total = len(cfg.pve_nodes)
    if reachable == total:
        ver_str = f" (PVE {pve_version})" if pve_version else ""
        fmt.step_ok(f"PVE cluster: {reachable}/{total} nodes{ver_str}")
        return 0
    elif reachable > 0:
        fmt.step_warn(f"PVE cluster: {reachable}/{total} nodes reachable")
        return 2
    else:
        fmt.step_fail(f"PVE cluster: 0/{total} nodes reachable")
        return 1
