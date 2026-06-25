"""Host scope helpers for runtime probes.

The config file may contain inventory rows that should be visible in the UI
but must not be treated as generic SSH-managed fleet targets.
"""

OPERATOR_AUTO_EXCLUDE_LABELS = {"nexus", "pve-freq"}


def should_probe_managed_host(cfg, host) -> bool:
    """Return True when a host should receive generic SSH health probes."""
    if not getattr(host, "managed", True):
        return False
    label = str(getattr(host, "label", "") or "").strip().lower()
    if label in OPERATOR_AUTO_EXCLUDE_LABELS:
        return False
    if (
        getattr(host, "htype", "") == "pve"
        and int(getattr(host, "vmid", 0) or 0)
        and getattr(host, "ip", "") not in set(getattr(cfg, "pve_nodes", []) or [])
    ):
        return False
    return True


def managed_probe_hosts(cfg):
    """Return configured hosts that are in scope for generic health probes."""
    return [h for h in (getattr(cfg, "hosts", []) or []) if should_probe_managed_host(cfg, h)]
