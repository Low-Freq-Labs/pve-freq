"""Security hardening for FREQ.

freq harden = freq audit --fix. Runs audit checks and applies fixes.
Also provides targeted hardening: SSH, firewall, packages.
"""
from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many


def cmd_harden(cfg: FreqConfig, pack, args) -> int:
    """Apply security hardening to fleet hosts."""
    target = getattr(args, "target", None)

    fmt.header("Harden")
    fmt.blank()

    # Resolve hosts
    if target and target.lower() != "all":
        host = resolve.by_target(cfg.hosts, target)
        if not host:
            fmt.error(f"Host not found: {target}")
            fmt.blank()
            fmt.footer()
            return 1
        hosts = [host]
    else:
        hosts = cfg.hosts

    if not hosts:
        fmt.error("No hosts to harden.")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.line(f"{fmt.C.BOLD}Hardening {len(hosts)} host(s)...{fmt.C.RESET}")
    fmt.blank()

    # Hardening checks — each returns (name, command, fix_command)
    checks = [
        (
            "SSH: Disable password auth",
            "grep -q '^PasswordAuthentication no' /etc/ssh/sshd_config && echo OK || echo DRIFT",
            "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config",
        ),
        (
            "SSH: Disable root login",
            "grep -q '^PermitRootLogin prohibit-password\\|^PermitRootLogin no' /etc/ssh/sshd_config && echo OK || echo DRIFT",
            "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config",
        ),
        (
            "SSH: Disable empty passwords",
            "grep -q '^PermitEmptyPasswords no' /etc/ssh/sshd_config && echo OK || echo DRIFT",
            "sed -i 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords no/' /etc/ssh/sshd_config",
        ),
        (
            "SSH: Set MaxAuthTries",
            "grep -q '^MaxAuthTries [0-5]' /etc/ssh/sshd_config && echo OK || echo DRIFT",
            "grep -q '^MaxAuthTries' /etc/ssh/sshd_config && sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config || echo 'MaxAuthTries 3' >> /etc/ssh/sshd_config",
        ),
        (
            "SSH: Disable X11 forwarding",
            "grep -q '^X11Forwarding no' /etc/ssh/sshd_config && echo OK || echo DRIFT",
            "sed -i 's/^#*X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config",
        ),
    ]

    total_fixed = 0
    total_ok = 0
    total_fail = 0
    ssh_restart_needed = set()

    for h in hosts:
        fmt.line(f"{fmt.C.PURPLE_BOLD}{h.label}{fmt.C.RESET}")

        for check_name, check_cmd, fix_cmd in checks:
            # Check current state
            r = ssh_run(
                host=h.ip, command=check_cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=10,
                htype=h.htype, use_sudo=True,
            )

            if r.returncode == 0 and "OK" in r.stdout:
                total_ok += 1
                print(f"    {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {check_name}")
            else:
                # Apply fix
                r = ssh_run(
                    host=h.ip, command=fix_cmd,
                    key_path=cfg.ssh_key_path,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=10,
                    htype=h.htype, use_sudo=True,
                )
                if r.returncode == 0:
                    total_fixed += 1
                    ssh_restart_needed.add(h.label)
                    print(f"    {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {check_name} — {fmt.C.GREEN}FIXED{fmt.C.RESET}")
                else:
                    total_fail += 1
                    print(f"    {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {check_name} — {fmt.C.RED}FAILED{fmt.C.RESET}")

    # Restart SSH where needed
    if ssh_restart_needed:
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Restarting SSH on {len(ssh_restart_needed)} host(s)...{fmt.C.RESET}")
        restart_hosts = [h for h in hosts if h.label in ssh_restart_needed]
        results = ssh_run_many(
            hosts=restart_hosts,
            command="systemctl restart sshd",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            max_parallel=cfg.ssh_max_parallel,
            use_sudo=True,
        )
        for h in restart_hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                fmt.step_ok(f"{h.label}: SSH restarted")
            else:
                fmt.step_fail(f"{h.label}: SSH restart failed")

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{total_ok}{fmt.C.RESET} ok  "
        f"{fmt.C.YELLOW}{total_fixed}{fmt.C.RESET} fixed  "
        f"{fmt.C.RED}{total_fail}{fmt.C.RESET} failed"
    )
    fmt.blank()
    fmt.footer()
    return 0 if total_fail == 0 else 1
