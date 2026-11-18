"""Fail-closed dashboard VM visibility policy independent of web transport."""


def _label_key(value):
    return str(value or "").strip().lower().replace("_", "-")


def _managed_dashboard_vm_identities(cfg):
    """Return managed VM identities allowed to appear in dashboard VM lists."""
    labels = set()
    vmids = set()
    for host in getattr(cfg, "hosts", []) or []:
        if not getattr(host, "managed", True):
            continue
        if getattr(host, "htype", "") == "pve":
            continue
        label = _label_key(getattr(host, "label", ""))
        if label:
            labels.add(label)
        try:
            vmid = int(getattr(host, "vmid", 0) or 0)
        except (TypeError, ValueError):
            vmid = 0
        if vmid:
            vmids.add(vmid)
    return labels, vmids


def _category_vmids(category):
    vmids = set()
    for vmid in category.get("vmids", []) or []:
        try:
            vmids.add(int(vmid))
        except (TypeError, ValueError):
            continue
    try:
        start = int(category.get("range_start"))
        end = int(category.get("range_end"))
    except (TypeError, ValueError):
        return vmids
    if start > end:
        start, end = end, start
    vmids.update(range(start, end + 1))
    return vmids


def _dashboard_vm_scope(cfg):
    """Return explicit dashboard VM visibility contract."""
    visible_vmids = set()
    hidden_vmids = set()
    fleet_boundaries = getattr(cfg, "fleet_boundaries", None)
    categories = getattr(fleet_boundaries, "categories", {}) or {}
    hidden_categories = {
        "out_of_contract",
        "discovered_unowned",
        "inventory_only",
        "unowned",
    }
    visible_categories = {
        "production",
        "lab",
        "infrastructure",
        "prod_media",
        "prod_other",
        "personal",
    }
    for name, category in categories.items():
        category_vmids = _category_vmids(category)
        if name in hidden_categories:
            hidden_vmids.update(category_vmids)
            continue
        if name == "templates":
            continue
        if name in visible_categories or str(category.get("tier", "")) in {"operator", "admin"}:
            visible_vmids.update(category_vmids)

    managed_labels, managed_vmids = _managed_dashboard_vm_identities(cfg)
    return {
        "visible_vmids": visible_vmids,
        "hidden_vmids": hidden_vmids,
        "managed_labels": managed_labels,
        "managed_vmids": managed_vmids,
        "has_boundary_contract": bool(visible_vmids or hidden_vmids),
    }


def _dashboard_vm_visible(vm, scope):
    """Dashboard VM cards are for operator-owned guests, not raw PVE inventory."""
    try:
        vmid = int((vm or {}).get("vmid", 0) or 0)
    except (TypeError, ValueError):
        vmid = 0
    if vmid and vmid in scope["hidden_vmids"]:
        return False
    if vmid and vmid in scope["visible_vmids"]:
        return True
    if scope["has_boundary_contract"]:
        return False
    if vmid and vmid in scope["managed_vmids"]:
        return True
    name = _label_key((vm or {}).get("name", ""))
    return bool(name and name in scope["managed_labels"])
