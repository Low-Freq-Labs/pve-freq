"""FREQ Doctor — self-diagnostic.

Checks everything FREQ needs to run: Python version, paths, config,
SSH key, connectivity, fleet data, PVE cluster, prerequisites.

Adapted from v1 doctor.sh (703 lines) — comprehensive and thorough.
"""
import os
import platform
import shutil
import subprocess
import sys

from freq.core.config import FreqConfig
from freq.core import fmt
from freq.core.ssh import run as ssh_run

# Doctor check timeouts
DOCTOR_CMD_TIMEOUT = 5
DOCTOR_PVE_TIMEOUT = 10


def run(cfg: FreqConfig) -> int:
    """Run all diagnostic checks. Returns 0 if all pass, 1 if any fail."""
    fmt.header("Doctor", "PVE FREQ")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Self-Diagnostic{fmt.C.RESET}")
    fmt.blank()

    passed = 0
    failed = 0
    warnings = 0

    sections = [
        ("System", [
            _check_python,
            _check_platform,
            _check_prerequisites,
        ]),
        ("Installation", [
            _check_install_dir,
            _check_config,
            _check_data_dirs,
            _check_personality,
        ]),
        ("SSH & Connectivity", [
            _check_ssh_binary,
            _check_ssh_key,
            _check_fleet_connectivity,
        ]),
        ("Fleet Data", [
            _check_hosts,
            _check_hosts_validity,
            _check_vlans,
            _check_distros,
        ]),
        ("PVE Cluster", [
            _check_pve_nodes,
        ]),
    ]

    for section_name, checks in sections:
        fmt.line(f"  {fmt.C.PURPLE_BOLD}{section_name}{fmt.C.RESET}")
        for check in checks:
            result = check(cfg)
            if result == 0:
                passed += 1
            elif result == 1:
                failed += 1
            else:
                warnings += 1
        print()

    fmt.divider("Summary")
    fmt.blank()

    total = passed + failed + warnings
    fmt.line(f"  {fmt.C.GREEN}{passed}{fmt.C.RESET} passed  "
             f"{fmt.C.YELLOW}{warnings}{fmt.C.RESET} warnings  "
             f"{fmt.C.RED}{failed}{fmt.C.RESET} failed  "
             f"({total} total)")
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
    dirs = [
        ("data", cfg.data_dir),
        ("data/log", os.path.dirname(cfg.log_file)),
        ("data/vault", cfg.vault_dir),
        ("data/keys", cfg.key_dir),
    ]
    all_ok = True
    for name, path in dirs:
        if os.path.isdir(path):
            if not os.access(path, os.W_OK):
                fmt.step_warn(f"Dir not writable: {name}")
                all_ok = False
        else:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                fmt.step_fail(f"Cannot create: {name}")
                return 1

    if all_ok:
        fmt.step_ok("Data directories")
    return 0 if all_ok else 2


def _check_personality(cfg: FreqConfig) -> int:
    pack_path = os.path.join(cfg.conf_dir, "personality", f"{cfg.build}.toml")
    if os.path.isfile(pack_path):
        fmt.step_ok(f"Personality: {cfg.build} pack")
        return 0
    else:
        fmt.step_warn(f"Personality: {cfg.build} pack not found")
        return 2


# --- SSH & Connectivity ---

def _check_ssh_binary(cfg: FreqConfig) -> int:
    if shutil.which("ssh"):
        try:
            result = subprocess.run(
                ["ssh", "-V"], capture_output=True, text=True, timeout=DOCTOR_CMD_TIMEOUT
            )
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
        if mode in ("600", "400"):
            fmt.step_ok(f"SSH key: {key_file} ({mode})")
            return 0
        else:
            fmt.step_warn(f"SSH key: {key_file} (permissions {mode}, should be 600)")
            return 2
    else:
        fmt.step_warn("SSH key: not found (fleet operations will fail)")
        return 2


def _check_fleet_connectivity(cfg: FreqConfig) -> int:
    """Quick connectivity test to first 3 hosts."""
    if not cfg.hosts:
        fmt.step_info("Fleet connectivity: no hosts to test")
        return 0

    sample = cfg.hosts[:3]
    reachable = 0
    for h in sample:
        r = ssh_run(
            host=h.ip, command="echo ok",
            key_path=cfg.ssh_key_path,
            connect_timeout=3, command_timeout=DOCTOR_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )
        if r.returncode == 0:
            reachable += 1

    if reachable == len(sample):
        fmt.step_ok(f"Fleet SSH: {reachable}/{len(sample)} sample hosts reachable")
        return 0
    elif reachable > 0:
        fmt.step_warn(f"Fleet SSH: {reachable}/{len(sample)} reachable")
        return 2
    else:
        fmt.step_fail(f"Fleet SSH: 0/{len(sample)} reachable")
        return 1


# --- Fleet Data ---

def _check_hosts(cfg: FreqConfig) -> int:
    if cfg.hosts:
        from freq.core.resolve import all_types
        types = all_types(cfg.hosts)
        type_str = ", ".join(f"{c} {t}" for t, c in sorted(types.items()))
        fmt.step_ok(f"Fleet: {len(cfg.hosts)} hosts ({type_str})")
        return 0
    elif os.path.isfile(cfg.hosts_file):
        fmt.step_warn("Fleet: hosts.conf exists but is empty")
        return 2
    else:
        fmt.step_warn("Fleet: no hosts.conf (run freq init)")
        return 2


def _check_hosts_validity(cfg: FreqConfig) -> int:
    """Check for duplicate IPs or labels in hosts.conf."""
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
        fmt.step_warn(f"Fleet data: {len(issues)} issue(s) — {issues[0]}")
        return 2
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
            host=ip, command="sudo pvesh get /version --output-format json 2>/dev/null || echo '{}'",
            key_path=cfg.ssh_key_path,
            connect_timeout=3, command_timeout=DOCTOR_PVE_TIMEOUT,
            htype="pve", use_sudo=False,
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
