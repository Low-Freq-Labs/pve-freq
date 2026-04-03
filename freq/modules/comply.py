"""CIS/STIG compliance scanning for FREQ.

Domain: freq secure <comply-scan|comply-status|comply-report|comply-exceptions>

Automated compliance checks against CIS Level 1 benchmarks for Linux hosts.
Scored pass/fail results per check, exception management for accepted risks,
and optional auto-remediation for safe fixes. No per-asset licensing fees.

Replaces: Nessus ($4,390/yr), Qualys ($20K+/yr for 100 assets),
          CIS-CAT Pro ($12K/yr)

Architecture:
    - CIS checks defined as data (id, title, command, remediation, severity)
    - Parallel SSH execution via ssh_run_many across fleet
    - Results and exceptions stored in conf/compliance/ as JSON
    - Remediation commands are cross-distro (uses platform install hints)

Design decisions:
    - Checks are data, not code. Adding a new CIS control means adding a
      dict entry, not writing a new function. Keeps the check library flat.
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

COMPLY_DIR = "compliance"
COMPLY_RESULTS = "scan-results.json"
COMPLY_EXCEPTIONS = "exceptions.json"
COMPLY_CMD_TIMEOUT = 20

# CIS Level 1 checks for Debian/Ubuntu
CIS_CHECKS = [
    {
        "id": "1.1.1",
        "title": "Ensure mounting of cramfs is disabled",
        "command": "modprobe -n -v cramfs 2>&1 | grep -q 'install /bin/true' && echo PASS || echo FAIL",
        "category": "filesystem",
        "severity": "medium",
        "remediation": "echo 'install cramfs /bin/true' >> /etc/modprobe.d/CIS.conf",
    },
    {
        "id": "1.4.1",
        "title": "Ensure permissions on bootloader config are configured",
        "command": "GRUB=$(test -f /boot/grub2/grub.cfg && echo /boot/grub2/grub.cfg || echo /boot/grub/grub.cfg); test -f $GRUB && stat -c '%a' $GRUB 2>/dev/null | grep -q '^[0-6][0-4][0-4]$' && echo PASS || echo FAIL",
        "category": "boot",
        "severity": "high",
        "remediation": "GRUB=$(test -f /boot/grub2/grub.cfg && echo /boot/grub2/grub.cfg || echo /boot/grub/grub.cfg); chmod 600 $GRUB",
    },
    {
        "id": "2.2.1",
        "title": "Ensure time synchronization is in use",
        "command": "systemctl is-active chronyd >/dev/null 2>&1 || systemctl is-active systemd-timesyncd >/dev/null 2>&1 || systemctl is-active ntp >/dev/null 2>&1 && echo PASS || echo FAIL",
        "category": "services",
        "severity": "medium",
        "remediation": "Install chrony: apt/dnf/pacman/apk install chrony, then enable chronyd",
    },
    {
        "id": "3.1.1",
        "title": "Ensure IP forwarding is disabled",
        "command": "sysctl net.ipv4.ip_forward 2>/dev/null | grep -q '= 0' && echo PASS || echo FAIL",
        "category": "network",
        "severity": "medium",
        "remediation": "sysctl -w net.ipv4.ip_forward=0",
    },
    {
        "id": "3.2.2",
        "title": "Ensure ICMP redirects are not accepted",
        "command": "sysctl net.ipv4.conf.all.accept_redirects 2>/dev/null | grep -q '= 0' && echo PASS || echo FAIL",
        "category": "network",
        "severity": "medium",
        "remediation": "sysctl -w net.ipv4.conf.all.accept_redirects=0",
    },
    {
        "id": "4.1.1",
        "title": "Ensure auditd is installed",
        "command": "dpkg -s auditd >/dev/null 2>&1 || rpm -q audit >/dev/null 2>&1 && echo PASS || echo FAIL",
        "category": "logging",
        "severity": "high",
        "remediation": "Install auditd: apt install auditd / dnf install audit / pacman -S audit",
    },
    {
        "id": "5.1.1",
        "title": "Ensure cron daemon is enabled and running",
        "command": "systemctl is-active cron >/dev/null 2>&1 || systemctl is-active crond >/dev/null 2>&1 && echo PASS || echo FAIL",
        "category": "access",
        "severity": "medium",
        "remediation": "systemctl enable --now cron",
    },
    {
        "id": "5.2.1",
        "title": "Ensure permissions on /etc/ssh/sshd_config are configured",
        "command": "stat -c '%a' /etc/ssh/sshd_config 2>/dev/null | grep -q '^600$' && echo PASS || echo FAIL",
        "category": "ssh",
        "severity": "high",
        "remediation": "chmod 600 /etc/ssh/sshd_config",
    },
    {
        "id": "5.2.4",
        "title": "Ensure SSH root login is disabled",
        "command": "grep -qi '^PermitRootLogin no' /etc/ssh/sshd_config && echo PASS || echo FAIL",
        "category": "ssh",
        "severity": "critical",
        "remediation": "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config && systemctl reload sshd",
    },
    {
        "id": "5.2.11",
        "title": "Ensure SSH MaxAuthTries is set to 4 or less",
        "command": "grep -qi '^MaxAuthTries [1-4]$' /etc/ssh/sshd_config && echo PASS || echo FAIL",
        "category": "ssh",
        "severity": "medium",
        "remediation": "sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 4/' /etc/ssh/sshd_config && systemctl reload sshd",
    },
    {
        "id": "5.4.1",
        "title": "Ensure password creation requirements are configured",
        "command": "grep -q 'minlen' /etc/security/pwquality.conf 2>/dev/null && echo PASS || echo FAIL",
        "category": "auth",
        "severity": "medium",
        "remediation": "echo 'minlen = 14' >> /etc/security/pwquality.conf",
    },
    {
        "id": "6.1.1",
        "title": "Ensure permissions on /etc/passwd are 644",
        "command": "stat -c '%a' /etc/passwd | grep -q '^644$' && echo PASS || echo FAIL",
        "category": "filesystem",
        "severity": "high",
        "remediation": "chmod 644 /etc/passwd",
    },
    {
        "id": "6.1.2",
        "title": "Ensure permissions on /etc/shadow are 640 or more restrictive",
        "command": "stat -c '%a' /etc/shadow | grep -qE '^(600|640)$' && echo PASS || echo FAIL",
        "category": "filesystem",
        "severity": "critical",
        "remediation": "chmod 640 /etc/shadow",
    },
    {
        "id": "6.2.1",
        "title": "Ensure no duplicate UIDs exist",
        "command": "awk -F: '{print $3}' /etc/passwd | sort | uniq -d | grep -q . && echo FAIL || echo PASS",
        "category": "auth",
        "severity": "critical",
        "remediation": "Manual review required — resolve duplicate UIDs in /etc/passwd",
    },
]


def _comply_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, COMPLY_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_results(cfg: FreqConfig) -> dict:
    filepath = os.path.join(_comply_dir(cfg), COMPLY_RESULTS)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"scans": [], "last_scan": ""}


def _save_results(cfg: FreqConfig, results: dict):
    filepath = os.path.join(_comply_dir(cfg), COMPLY_RESULTS)
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2)


def _load_exceptions(cfg: FreqConfig) -> list:
    filepath = os.path.join(_comply_dir(cfg), COMPLY_EXCEPTIONS)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_exceptions(cfg: FreqConfig, exceptions: list):
    filepath = os.path.join(_comply_dir(cfg), COMPLY_EXCEPTIONS)
    with open(filepath, "w") as f:
        json.dump(exceptions, f, indent=2)


def _is_excepted(exceptions: list, check_id: str, host: str) -> bool:
    """Check if a finding has an exception."""
    for exc in exceptions:
        if exc.get("check_id") == check_id and (exc.get("host") == host or exc.get("host") == "*"):
            return True
    return False


def cmd_comply(cfg: FreqConfig, pack, args) -> int:
    """Compliance management dispatch."""
    action = getattr(args, "action", None) or "scan"
    routes = {
        "scan": _cmd_scan,
        "status": _cmd_status,
        "report": _cmd_report,
        "exceptions": _cmd_exceptions,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown comply action: {action}")
    fmt.info("Available: scan, status, report, exceptions")
    return 1


def _cmd_scan(cfg: FreqConfig, args) -> int:
    """Run compliance scan across fleet."""
    fmt.header("Compliance Scan — CIS Level 1")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Build compound check command
    check_cmds = []
    for check in CIS_CHECKS:
        safe_cmd = check["command"].replace('"', '\\"')
        check_cmds.append(f'echo "{check["id"]}|$({safe_cmd})"')

    command = "; ".join(check_cmds)

    fmt.step_start(f"Scanning {len(hosts)} hosts against {len(CIS_CHECKS)} checks")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=COMPLY_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )
    fmt.step_ok("Scan complete")
    fmt.blank()

    exceptions = _load_exceptions(cfg)
    scan_data = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "hosts": {}}

    total_pass = 0
    total_fail = 0
    total_checks = 0

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {h.label}: unreachable")
            continue

        host_pass = 0
        host_fail = 0
        host_results = {}

        for line in r.stdout.strip().split("\n"):
            if "|" not in line:
                continue
            check_id, result = line.split("|", 1)
            check_id = check_id.strip()
            result = result.strip()

            total_checks += 1
            host_results[check_id] = result

            if result == "PASS":
                host_pass += 1
                total_pass += 1
            else:
                if _is_excepted(exceptions, check_id, h.label):
                    host_pass += 1  # Excepted = counted as pass
                    total_pass += 1
                else:
                    host_fail += 1
                    total_fail += 1

        scan_data["hosts"][h.label] = host_results
        host_total = host_pass + host_fail
        score = round(host_pass / max(host_total, 1) * 100, 1)
        color = fmt.C.GREEN if score >= 90 else (fmt.C.YELLOW if score >= 70 else fmt.C.RED)

        fmt.line(f"  {color}{score:5.1f}%{fmt.C.RESET} {fmt.C.BOLD}{h.label}{fmt.C.RESET} "
                 f"({host_pass}/{host_total} pass, {host_fail} fail)")

    # Save results
    all_results = _load_results(cfg)
    all_results["scans"].append(scan_data)
    all_results["scans"] = all_results["scans"][-50:]  # Keep last 50 scans
    all_results["last_scan"] = scan_data["timestamp"]
    _save_results(cfg, all_results)

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()

    fleet_score = round(total_pass / max(total_checks, 1) * 100, 1)
    fleet_color = fmt.C.GREEN if fleet_score >= 90 else (fmt.C.YELLOW if fleet_score >= 70 else fmt.C.RED)

    fmt.line(f"  Fleet Compliance: {fleet_color}{fmt.C.BOLD}{fleet_score}%{fmt.C.RESET}")
    fmt.line(f"  Checks:  {total_checks} ({total_pass} pass, {total_fail} fail)")
    fmt.line(f"  Hosts:   {len(hosts)}")
    fmt.line(f"  Rules:   {len(CIS_CHECKS)} CIS Level 1 checks")
    fmt.blank()
    fmt.footer()
    return 0 if total_fail == 0 else 1


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Show compliance status from last scan."""
    fmt.header("Compliance Status")
    fmt.blank()

    results = _load_results(cfg)
    last_scan = results.get("last_scan", "never")

    fmt.line(f"  Last scan: {last_scan}")
    fmt.line(f"  Checks:    {len(CIS_CHECKS)} CIS Level 1")
    fmt.line(f"  Benchmark: Debian/Ubuntu CIS Level 1")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Run scan: freq comply scan{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_report(cfg: FreqConfig, args) -> int:
    """Generate compliance report."""
    results = _load_results(cfg)
    if not results.get("scans"):
        fmt.error("No scan data. Run: freq comply scan")
        return 1

    if getattr(args, "json", False):
        print(json.dumps(results, indent=2))
        return 0

    fmt.header("Compliance Report")
    fmt.blank()

    latest = results["scans"][-1]
    fmt.line(f"  Scan time: {latest.get('timestamp', '?')}")
    fmt.blank()

    fmt.table_header(("ID", 8), ("TITLE", 40), ("SEVERITY", 10), ("RESULT", 8))

    for check in CIS_CHECKS:
        # Find result from any host (show worst case)
        worst = "PASS"
        for host_data in latest.get("hosts", {}).values():
            result = host_data.get(check["id"], "SKIP")
            if result == "FAIL":
                worst = "FAIL"
                break

        color = fmt.C.GREEN if worst == "PASS" else fmt.C.RED
        fmt.table_row(
            (check["id"], 8),
            (check["title"][:40], 40),
            (check["severity"], 10),
            (f"{color}{worst}{fmt.C.RESET}", 8),
        )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_exceptions(cfg: FreqConfig, args) -> int:
    """Manage compliance exceptions."""
    fmt.header("Compliance Exceptions")
    fmt.blank()

    exceptions = _load_exceptions(cfg)
    if not exceptions:
        fmt.line(f"  {fmt.C.DIM}No exceptions configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Add one by editing {os.path.join(_comply_dir(cfg), COMPLY_EXCEPTIONS)}{fmt.C.RESET}")
    else:
        fmt.table_header(("CHECK", 8), ("HOST", 14), ("REASON", 30))
        for exc in exceptions:
            fmt.table_row(
                (exc.get("check_id", ""), 8),
                (exc.get("host", "*"), 14),
                (exc.get("reason", "")[:30], 30),
            )

    fmt.blank()
    fmt.footer()
    return 0
