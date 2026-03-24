"""Fleet resolver — reads FREQ's hosts.conf.

This is the bridge between FREQ's bash-native fleet registry and the
Python engine. No separate config — we read what bash already knows.

hosts.conf format per line: IP LABEL TYPE [GROUPS]
Lines starting with # are comments.
"""
import os
from engine.core.types import Host


def load_fleet(hosts_file: str = "", freq_dir: str = "") -> list[Host]:
    """Load fleet from hosts.conf.

    Args:
        hosts_file: Direct path to hosts.conf (takes priority)
        freq_dir: FREQ install dir (used to derive hosts.conf path)

    Returns:
        List of Host objects
    """
    if not hosts_file:
        hosts_file = os.path.join(freq_dir or "/opt/pve-freq", "conf", "hosts.conf")

    hosts = []
    if not os.path.exists(hosts_file):
        return hosts

    with open(hosts_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                hosts.append(Host(
                    ip=parts[0],
                    label=parts[1],
                    htype=parts[2],
                    groups=parts[3] if len(parts) > 3 else "",
                ))
    return hosts


def filter_by_scope(hosts: list[Host], scope: list[str]) -> list[Host]:
    """Filter hosts to those matching the policy scope.

    Args:
        hosts: Full fleet list
        scope: List of host types the policy applies to

    Returns:
        Filtered list of hosts within scope
    """
    return [h for h in hosts if h.htype in scope]


def filter_by_labels(hosts: list[Host], labels: list[str]) -> list[Host]:
    """Filter hosts to specific labels.

    Args:
        hosts: Fleet list
        labels: Host labels to keep (empty = keep all)

    Returns:
        Filtered list matching requested labels
    """
    if not labels:
        return hosts
    return [h for h in hosts if h.label in labels]


def filter_by_groups(hosts: list[Host], groups: list[str]) -> list[Host]:
    """Filter hosts by group membership.

    Args:
        hosts: Fleet list
        groups: Group names to match

    Returns:
        Hosts that belong to any of the specified groups
    """
    if not groups:
        return hosts
    result = []
    for h in hosts:
        host_groups = [g.strip() for g in h.groups.split(",") if g.strip()]
        if any(g in host_groups for g in groups):
            result.append(h)
    return result
