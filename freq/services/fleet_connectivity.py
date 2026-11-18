"""Fleet connectivity projection below dashboard HTTP transport."""

from freq.core.device_credentials import resolve_staged_device_ssh_auth
from freq.core.health_state import STATE_AUTH_FAILED, STATE_UNREACHABLE
from freq.core.ssh import run as ssh_single


def probe_fleet_connectivity(cfg, health):
    """Project cached fleet truth and probe only hosts absent from that cache."""
    health_by_ip = {}
    if isinstance(health, dict):
        for row in health.get("hosts", []) or []:
            if isinstance(row, dict) and row.get("ip"):
                health_by_ip[row["ip"]] = row

    hosts = []
    for host in cfg.hosts:
        host_type = getattr(host, "htype", "linux")
        cached = health_by_ip.get(host.ip)
        if cached:
            state = cached.get("state") or cached.get("status")
            reachable = state not in {STATE_AUTH_FAILED, STATE_UNREACHABLE}
            hosts.append(
                {
                    "label": host.label,
                    "ip": host.ip,
                    "type": host_type,
                    "reachable": reachable,
                    "user": cached.get("state") or cached.get("status") or "",
                    "state": state,
                    "reason": cached.get("reason", ""),
                    "source": "health_cache",
                }
            )
            continue

        legacy_types = {"idrac", "switch"}
        command = "whoami"
        key = cfg.ssh_key_path
        user = cfg.ssh_service_account
        local_user = None
        password_file = None
        sudo_password_file = False
        if host_type in ("pfsense", "idrac", "switch", "truenas"):
            auth = resolve_staged_device_ssh_auth(cfg, host_type)
            key = auth.get("key_path") or (
                (cfg.ssh_rsa_key_path or cfg.ssh_key_path)
                if host_type in legacy_types
                else cfg.ssh_key_path
            )
            user = auth.get("user") or None
            local_user = auth.get("local_user") or None
            password_file = auth.get("password_file") or None
            sudo_password_file = auth.get("sudo_password_file", False)
            if host_type == "pfsense":
                command = "echo OK"
            elif host_type == "idrac":
                command = "racadm getversion"
            elif host_type == "switch":
                command = "show version | include uptime"

        try:
            result = ssh_single(
                host=host.ip,
                command=command,
                key_path=key,
                user=user,
                local_user=local_user,
                password_file=password_file,
                sudo_password_file=sudo_password_file,
                connect_timeout=3,
                command_timeout=5,
                htype=host_type,
                cfg=cfg,
            )
            reachable = result.returncode == 0
            user = result.stdout.strip() if reachable else ""
        except Exception:
            reachable = False
            user = ""

        hosts.append(
            {
                "label": host.label,
                "ip": host.ip,
                "type": host_type,
                "reachable": reachable,
                "user": user,
            }
        )

    return {
        "hosts": hosts,
        "total": len(hosts),
        "reachable": sum(1 for host in hosts if host["reachable"]),
    }
