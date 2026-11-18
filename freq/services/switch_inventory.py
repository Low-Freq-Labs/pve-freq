"""Downward-owned switch inventory selection."""


def _get_switch_hosts(cfg):
    """Return all hosts with htype=switch from hosts.toml."""
    return [h for h in cfg.hosts if h.htype == "switch"]
