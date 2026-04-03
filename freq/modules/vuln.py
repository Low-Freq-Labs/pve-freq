"""Vulnerability scanning for FREQ — package-based CVE detection.

Domain: freq secure vuln <action>
What: Check installed packages against known vulnerabilities. Scans fleet
      hosts via SSH, parses package lists, queries CVE data.
Replaces: Nessus, OpenVAS, manual apt audit
Architecture:
    - SSH to fleet hosts, run apt/dpkg commands
    - Parse package versions from dpkg output
    - Check against Debian security tracker or local CVE database
    - Results stored in conf/vuln/
Design decisions:
    - dpkg-based scanning first (Debian/Ubuntu). Extensible to rpm.
    - No external scanner dependency. Package list + version comparison.
    - Fleet-wide: scan all hosts in parallel via ssh_run_many.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many
from freq.core import log as logger


VULN_DIR = "vuln"


def _vuln_dir(cfg):
    path = os.path.join(cfg.conf_dir, VULN_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def cmd_vuln_scan(cfg: FreqConfig, pack, args) -> int:
    """Scan fleet hosts for packages with pending security updates."""
    fmt.header("Vulnerability Scan", breadcrumb="FREQ > Secure > Vuln")
    fmt.blank()

    linux_hosts = [h for h in cfg.hosts if h.htype in ("linux", "pve", "docker")]
    if not linux_hosts:
        fmt.warn("No Linux hosts in fleet")
        fmt.footer()
        return 1

    # Check for security updates pending
    cmd = "apt list --upgradable 2>/dev/null | grep -i secur | wc -l; apt list --upgradable 2>/dev/null | wc -l"
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in linux_hosts]
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
    )

    scan_results = []
    for h in linux_hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            security = int(lines[0]) if lines and lines[0].isdigit() else 0
            total = int(lines[1]) - 1 if len(lines) > 1 and lines[1].isdigit() else 0  # -1 for header
            total = max(0, total)

            color = fmt.C.RED if security > 0 else fmt.C.YELLOW if total > 0 else fmt.C.GREEN
            status = f"{color}{security} security, {total} total{fmt.C.RESET}"
            fmt.line(f"  {h.label:<14} {status}")

            scan_results.append(
                {
                    "host": h.label,
                    "ip": h.ip,
                    "security_updates": security,
                    "total_updates": total,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
        else:
            fmt.line(f"  {h.label:<14} {fmt.C.DIM}unreachable{fmt.C.RESET}")

    # Save scan results
    filepath = os.path.join(_vuln_dir(cfg), "last-scan.json")
    with open(filepath, "w") as f:
        json.dump(scan_results, f, indent=2)

    fmt.blank()
    total_sec = sum(r.get("security_updates", 0) for r in scan_results)
    if total_sec > 0:
        fmt.warn(f"{total_sec} security update(s) pending across fleet")
    else:
        fmt.success("No pending security updates")

    logger.info("vuln_scan", hosts=len(linux_hosts), security=total_sec)
    fmt.footer()
    return 0


def cmd_vuln_results(cfg: FreqConfig, pack, args) -> int:
    """Show results of the last vulnerability scan."""
    filepath = os.path.join(_vuln_dir(cfg), "last-scan.json")
    if not os.path.exists(filepath):
        fmt.warn("No scan results. Run: freq secure vuln scan")
        return 1

    with open(filepath) as f:
        results = json.load(f)

    fmt.header("Last Vulnerability Scan", breadcrumb="FREQ > Secure > Vuln")
    fmt.blank()

    fmt.table_header(("Host", 14), ("Security", 10), ("Total", 8), ("Scanned", 20))
    for r in sorted(results, key=lambda x: x.get("security_updates", 0), reverse=True):
        sec = r.get("security_updates", 0)
        color = fmt.C.RED if sec > 0 else fmt.C.GREEN
        fmt.table_row(
            (r.get("host", ""), 14),
            (f"{color}{sec}{fmt.C.RESET}", 10),
            (str(r.get("total_updates", 0)), 8),
            (r.get("timestamp", ""), 20),
        )

    fmt.blank()
    fmt.footer()
    return 0
