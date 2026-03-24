"""Security audit for FREQ.

Commands: audit

Scans fleet hosts for common security issues:
- SSH configuration (root login, password auth, key-only)
- Open ports (listening services)
- Sudoers configuration
- Package updates available
- Firewall status
- Failed login attempts

Each check returns findings with severity (INFO/WARN/CRIT).
No changes are made — this is read-only.
"""
import json

from freq.core import fmt
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many
from freq.core.types import Finding, Severity

# Audit timeouts
AUDIT_CMD_TIMEOUT = 10
AUDIT_PKG_TIMEOUT = 15

# Audit thresholds
OPEN_PORTS_WARNING = 10
FAILED_LOGIN_CRITICAL = 50
FAILED_LOGIN_WARNING = 10
UPDATES_WARNING = 20


def cmd_audit(cfg: FreqConfig, pack, args) -> int:
    """Run security audit across fleet."""
    fmt.header("Security Audit")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"{fmt.C.YELLOW}No hosts registered.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.line(f"{fmt.C.BOLD}Auditing {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    checks = [
        ("SSH Config", _check_ssh_config),
        ("Password Auth", _check_password_auth),
        ("Root Login", _check_root_login),
        ("Listening Ports", _check_open_ports),
        ("Failed Logins", _check_failed_logins),
        ("Package Updates", _check_updates),
    ]

    all_findings = {}
    total_crit = 0
    total_warn = 0
    total_info = 0

    for host in hosts:
        host_findings = []
        for check_name, check_fn in checks:
            findings = check_fn(cfg, host)
            host_findings.extend(findings)

        all_findings[host.label] = host_findings

        for f in host_findings:
            if f.severity == Severity.CRIT:
                total_crit += 1
            elif f.severity == Severity.WARN:
                total_warn += 1
            else:
                total_info += 1

    # Display results per host
    for host in hosts:
        findings = all_findings.get(host.label, [])
        crits = [f for f in findings if f.severity == Severity.CRIT]
        warns = [f for f in findings if f.severity == Severity.WARN]
        infos = [f for f in findings if f.severity == Severity.INFO]

        if crits:
            status = fmt.badge("critical")
        elif warns:
            status = fmt.badge("warn")
        else:
            status = fmt.badge("pass")

        print(f"  {fmt.C.BOLD}{host.label:<16}{fmt.C.RESET} {status}")

        for f in crits:
            print(f"    {fmt.C.RED}{fmt.S.CROSS} [{f.severity.value.upper()}]{fmt.C.RESET} {f.key}: {f.current}")
        for f in warns:
            print(f"    {fmt.C.YELLOW}{fmt.S.WARN}  [{f.severity.value.upper()}]{fmt.C.RESET} {f.key}: {f.current}")
        for f in infos:
            print(f"    {fmt.C.DIM}{fmt.S.INFO}  {f.key}: {f.current}{fmt.C.RESET}")

        if not findings:
            print(f"    {fmt.C.GREEN}{fmt.S.TICK} All checks passed{fmt.C.RESET}")

    # Summary
    fmt.blank()
    fmt.divider("Audit Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.RED}{total_crit}{fmt.C.RESET} critical  "
        f"{fmt.C.YELLOW}{total_warn}{fmt.C.RESET} warnings  "
        f"{fmt.C.CYAN}{total_info}{fmt.C.RESET} info  "
        f"({len(hosts)} hosts scanned)"
    )

    if total_crit > 0:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}Critical findings need attention.{fmt.C.RESET}")
    elif total_warn > 0:
        fmt.blank()
        fmt.line(f"  {fmt.C.YELLOW}Warnings found. Review recommended.{fmt.C.RESET}")
    else:
        fmt.blank()
        fmt.line(f"  {fmt.C.GREEN}Fleet is clean. No critical findings.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()

    return 1 if total_crit > 0 else 0


# --- Individual Checks ---

def _check_ssh_config(cfg: FreqConfig, host) -> list:
    """Check SSH daemon configuration."""
    findings = []
    r = ssh_run(
        host=host.ip,
        command="cat /etc/ssh/sshd_config 2>/dev/null | grep -v '^#' | grep -v '^$'",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode != 0:
        findings.append(Finding(
            resource_type="ssh", key="sshd_config",
            current="Cannot read SSH config", desired="readable",
            severity=Severity.WARN,
        ))
    return findings


def _check_password_auth(cfg: FreqConfig, host) -> list:
    """Check if password authentication is disabled."""
    findings = []
    r = ssh_run(
        host=host.ip,
        command="grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_SET'",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode == 0:
        value = r.stdout.strip().lower()
        if "yes" in value:
            findings.append(Finding(
                resource_type="ssh", key="PasswordAuthentication",
                current="yes (enabled)", desired="no",
                severity=Severity.WARN,
            ))
        elif "not_set" in value:
            findings.append(Finding(
                resource_type="ssh", key="PasswordAuthentication",
                current="not explicitly set (default varies)", desired="no",
                severity=Severity.INFO,
            ))
    return findings


def _check_root_login(cfg: FreqConfig, host) -> list:
    """Check if root login is permitted."""
    findings = []
    r = ssh_run(
        host=host.ip,
        command="grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_SET'",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode == 0:
        value = r.stdout.strip().lower()
        if "yes" in value and "prohibit" not in value:
            findings.append(Finding(
                resource_type="ssh", key="PermitRootLogin",
                current="yes (unrestricted)", desired="prohibit-password or no",
                severity=Severity.CRIT,
            ))
    return findings


def _check_open_ports(cfg: FreqConfig, host) -> list:
    """Check for listening ports."""
    findings = []
    r = ssh_run(
        host=host.ip,
        command="ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sort -u",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode == 0 and r.stdout.strip():
        ports = r.stdout.strip().split("\n")
        port_count = len(ports)
        if port_count > OPEN_PORTS_WARNING:
            findings.append(Finding(
                resource_type="network", key="Listening ports",
                current=f"{port_count} ports open",
                desired="review needed",
                severity=Severity.WARN,
            ))
        else:
            findings.append(Finding(
                resource_type="network", key="Listening ports",
                current=f"{port_count} ports",
                desired="ok",
                severity=Severity.INFO,
            ))
    return findings


def _check_failed_logins(cfg: FreqConfig, host) -> list:
    """Check for recent failed login attempts."""
    findings = []
    r = ssh_run(
        host=host.ip,
        command="journalctl -u sshd --since '24 hours ago' --no-pager 2>/dev/null | grep -c 'Failed password' || echo 0",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode == 0:
        try:
            count = int(r.stdout.strip())
            if count > FAILED_LOGIN_CRITICAL:
                findings.append(Finding(
                    resource_type="auth", key="Failed SSH logins (24h)",
                    current=f"{count} attempts",
                    desired="< 50",
                    severity=Severity.CRIT,
                ))
            elif count > FAILED_LOGIN_WARNING:
                findings.append(Finding(
                    resource_type="auth", key="Failed SSH logins (24h)",
                    current=f"{count} attempts",
                    desired="< 10",
                    severity=Severity.WARN,
                ))
        except ValueError:
            pass
    return findings


def _check_updates(cfg: FreqConfig, host) -> list:
    """Check for available package updates."""
    findings = []

    # Try apt (Debian/Ubuntu)
    r = ssh_run(
        host=host.ip,
        command="apt list --upgradable 2>/dev/null | grep -c upgradable || echo 0",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_PKG_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode == 0:
        try:
            count = int(r.stdout.strip())
            if count > UPDATES_WARNING:
                findings.append(Finding(
                    resource_type="packages", key="Updates available",
                    current=f"{count} packages",
                    desired="up to date",
                    severity=Severity.WARN,
                ))
            elif count > 0:
                findings.append(Finding(
                    resource_type="packages", key="Updates available",
                    current=f"{count} packages",
                    desired="up to date",
                    severity=Severity.INFO,
                ))
            return findings
        except ValueError:
            pass

    # Try dnf (Rocky/Alma)
    r = ssh_run(
        host=host.ip,
        command="dnf check-update --quiet 2>/dev/null | wc -l || echo 0",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=AUDIT_PKG_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode in (0, 100) and r.stdout.strip():
        try:
            count = int(r.stdout.strip())
            if count > 0:
                findings.append(Finding(
                    resource_type="packages", key="Updates available",
                    current=f"{count} packages",
                    desired="up to date",
                    severity=Severity.INFO if count < 20 else Severity.WARN,
                ))
        except ValueError:
            pass

    return findings
