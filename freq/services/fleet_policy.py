"""Fleet permission policy shared by transport adapters."""


def check_vm_permission(cfg, vmid, action):
    """Return whether ``action`` is allowed for ``vmid`` and an honest error."""
    boundaries = cfg.fleet_boundaries
    category, tier = boundaries.categorize(vmid)
    if boundaries.can_action(vmid, action):
        return True, ""
    return False, f"Action '{action}' blocked on VMID {vmid} ({category}/{tier})"
