"""Host scope helpers for runtime probes.

The config file may contain inventory rows that should be visible in the UI
but must not be treated as generic SSH-managed fleet targets.
"""

import os

OPERATOR_AUTO_EXCLUDE_LABELS = {"nexus", "pve-freq"}


def should_probe_managed_host(cfg, host) -> bool:
    """Return True when a host should receive generic SSH health probes."""
    if not getattr(host, "managed", True):
        return False
    label = str(getattr(host, "label", "") or "").strip().lower()
    if label in OPERATOR_AUTO_EXCLUDE_LABELS:
        return False
    vmid = _resolve_host_vmid(cfg, host)
    category = _fleet_category(cfg, vmid)
    if category in {"out_of_contract", "templates"}:
        return False
    if (
        getattr(host, "htype", "") == "pve"
        and vmid
        and getattr(host, "ip", "") not in set(getattr(cfg, "pve_nodes", []) or [])
    ):
        return False
    return True


def managed_probe_hosts(cfg):
    """Return configured hosts that are in scope for generic health probes."""
    return [h for h in (getattr(cfg, "hosts", []) or []) if should_probe_managed_host(cfg, h)]


def _fleet_category(cfg, vmid: int) -> str:
    if not vmid:
        return ""
    boundaries = getattr(cfg, "fleet_boundaries", None)
    if not boundaries or not hasattr(boundaries, "categorize"):
        return ""
    try:
        category, _tier = boundaries.categorize(vmid)
        return category or ""
    except Exception:
        return ""


def _resolve_host_vmid(cfg, host) -> int:
    """Resolve a host VMID from hosts.toml or the generated PVE inventory."""
    direct = int(getattr(host, "vmid", 0) or 0)
    if direct:
        return direct
    label = str(getattr(host, "label", "") or "").strip().lower()
    ips = set([str(getattr(host, "ip", "") or "").strip()])
    ips.update(str(ip).strip() for ip in (getattr(host, "all_ips", []) or []) if ip)
    for item in _pve_inventory_resources(cfg):
        name = str(item.get("name", "") or "").strip().lower()
        vmid = int(item.get("vmid", 0) or 0)
        if vmid and label and name == label:
            return vmid
        item_ips = item.get("ips") or item.get("all_ips") or []
        if isinstance(item_ips, str):
            item_ips = [item_ips]
        if vmid and ips and ips.intersection(str(ip).strip() for ip in item_ips if ip):
            return vmid
    return 0


def _pve_inventory_resources(cfg) -> list:
    conf_dir = getattr(cfg, "conf_dir", "") or ""
    path = os.path.join(conf_dir, "pve-inventory.toml") if conf_dir else ""
    if not path or not os.path.isfile(path):
        return []
    try:
        from freq.core.config import load_toml

        data = load_toml(path)
    except Exception:
        return []
    return data.get("resource", []) or data.get("vm", []) or []
