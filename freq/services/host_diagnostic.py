"""Host diagnostic resolution and execution below dashboard HTTP transport."""

import re

from freq.core import log as logger
from freq.core import resolve
from freq.core.ssh import run as ssh_single
from freq.core.types import Host

DIAGNOSTIC_COMMAND = (
    'echo "=== SYSTEM ===" && hostname -f && cat /etc/os-release 2>/dev/null | grep PRETTY && uname -r '
    '&& echo "=== RESOURCES ===" && nproc && free -h | head -2 && df -h / && cat /proc/loadavg '
    '&& echo "=== NETWORK ===" && ip -4 addr show | grep inet | grep -v 127 && ip route show default '
    '&& echo "=== DOCKER ===" && docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "not installed" '
    '&& echo "=== SECURITY ===" && systemctl --failed --no-legend 2>/dev/null | head -5 || echo "ok" '
    '&& echo "=== LISTENING ===" && ss -tlnp 2>/dev/null | grep LISTEN | head -10'
)


def run_host_diagnostic(
    cfg,
    target,
    *,
    find_live_vm_node_ip,
    guest_agent_network_json,
    extract_guest_ipv4,
):
    """Resolve one host, execute its diagnostic, and return payload plus status."""
    if not target:
        return {"error": "target required"}, 400

    host = resolve.by_target(cfg.hosts, target)
    vm_match = re.match(r"^vm:(\d+)$", str(target or "").strip(), re.I)
    if not host and vm_match:
        vmid = int(vm_match.group(1))
        for known in cfg.hosts:
            if int(getattr(known, "vmid", 0) or 0) == vmid:
                host = known
                break
        if not host:
            try:
                node_ip, node_name = find_live_vm_node_ip(cfg, vmid, "")
                if node_ip:
                    raw, ok, _method = guest_agent_network_json(
                        cfg,
                        vmid,
                        node_ip,
                        node_name,
                    )
                    if ok:
                        guest_ip = extract_guest_ipv4(raw)
                        if guest_ip:
                            host = Host(
                                ip=guest_ip,
                                label=f"vm-{vmid}",
                                htype="linux",
                                groups="ad-hoc-vm",
                                vmid=vmid,
                            )
            except Exception as error:
                logger.warn(
                    f"host diagnostic VM target resolve failed for VMID {vmid}: {error}"
                )
    if not host and re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", target):
        host = Host(ip=target, label=target, htype="linux", groups="ad-hoc-vm")
    if not host:
        return {"error": f"Host not found: {target}"}, 404

    result = ssh_single(
        host=host.ip,
        command=DIAGNOSTIC_COMMAND,
        key_path=cfg.ssh_key_path,
        connect_timeout=5,
        command_timeout=15,
        htype=host.htype,
        use_sudo=True,
        cfg=cfg,
    )
    return {
        "host": target,
        "output": result.stdout if result else "",
        "ok": result is not None and result.returncode == 0,
    }, None
