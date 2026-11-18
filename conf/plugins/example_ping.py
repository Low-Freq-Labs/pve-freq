"""Example FREQ plugin — ping a host and report latency.

Drop this in conf/plugins/ and it's automatically available as: freq ping <host>
"""
import subprocess

NAME = "ping"
DESCRIPTION = "Ping a host and show latency"


def run(cfg, pack, args):
    """Ping handler — demonstrates the plugin interface."""
    from freq.core import fmt

    plugin_args = getattr(args, "plugin_args", [])
    target = plugin_args[0] if plugin_args else None

    if not target:
        fmt.error("Usage: freq ping <host-or-ip>")
        return 1

    # Resolve label to IP
    from freq.core.resolve import by_target
    host = by_target(cfg.hosts, target)
    ip = host.ip if host else target
    label = host.label if host else target

    fmt.header(f"Ping: {label}")
    fmt.blank()

    r = subprocess.run(
        ["ping", "-c", "3", "-W", "2", ip],
        capture_output=True, text=True, timeout=15,
    )

    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            if "time=" in line or "rtt" in line or "packets" in line:
                print(f"  {fmt.C.GREEN}{line}{fmt.C.RESET}")
            else:
                print(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.error(f"Ping failed: {ip}")

    fmt.blank()
    fmt.footer()
    return r.returncode
