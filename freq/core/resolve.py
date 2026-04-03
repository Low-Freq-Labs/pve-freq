"""Host resolution for FREQ — the address book.

Provides: by_label(), by_ip(), by_group(), resolve_target()

The address book. Name to IP, label to Host, group to hosts, "all" to fleet.
Every command that targets a host goes through here first. Fuzzy matching
handles typos and partial labels.

Replaces: Manual IP lookups, Ansible inventory group resolution

Architecture:
    - Pure functions operating on the cfg.hosts list — no state, no I/O
    - Case-insensitive label matching, partial prefix matching
    - Group resolution returns list of Host objects for fleet exec

Design decisions:
    - Resolution is strict by default. "lab" won't match "lab-pve1" unless
      there's no exact match. Prevents accidental fleet-wide commands.
    - "all" is a special keyword that returns every host. No group needed.
"""
from typing import Optional

from freq.core.types import Host, ContainerVM


def by_label(hosts: list, label: str) -> Optional[Host]:
    """Find a host by its label (case-insensitive)."""
    label_lower = label.lower()
    for h in hosts:
        if h.label.lower() == label_lower:
            return h
    return None


def by_ip(hosts: list, ip: str) -> Optional[Host]:
    """Find a host by its primary IP or any IP in all_ips."""
    for h in hosts:
        if h.ip == ip:
            return h
        all_ips = getattr(h, "all_ips", []) or []
        if ip in all_ips:
            return h
    return None


def by_target(hosts: list, target: str) -> Optional[Host]:
    """Find a host by label or IP (tries both)."""
    # Try label first (more common)
    host = by_label(hosts, target)
    if host:
        return host
    # Try IP
    return by_ip(hosts, target)


def by_group(hosts: list, group: str) -> list:
    """Find all hosts in a group."""
    group_lower = group.lower()
    return [h for h in hosts if group_lower in h.groups.lower().split(",")]


def by_type(hosts: list, htype: str) -> list:
    """Find all hosts of a given type."""
    htype_lower = htype.lower()
    return [h for h in hosts if h.htype.lower() == htype_lower]


def by_scope(hosts: list, scope: list) -> list:
    """Filter hosts to those matching any type in the scope list.

    Used by the policy engine to find applicable hosts.
    """
    scope_lower = [s.lower() for s in scope]
    return [h for h in hosts if h.htype.lower() in scope_lower]


def by_labels(hosts: list, labels: str) -> list:
    """Filter hosts by comma-separated labels."""
    label_list = [l.strip().lower() for l in labels.split(",")]
    return [h for h in hosts if h.label.lower() in label_list]


def all_groups(hosts: list) -> dict:
    """Get all groups and their member hosts."""
    groups = {}
    for h in hosts:
        if not h.groups:
            continue
        for g in h.groups.split(","):
            g = g.strip()
            if g not in groups:
                groups[g] = []
            groups[g].append(h)
    return groups


def all_types(hosts: list) -> dict:
    """Get all host types and their counts."""
    types = {}
    for h in hosts:
        types[h.htype] = types.get(h.htype, 0) + 1
    return types


# --- Container Resolution ---

def container_by_name(container_vms: dict, name: str) -> tuple:
    """Find a container by name across all VMs.

    Returns (Container, ContainerVM) or (None, None).
    """
    name_lower = name.lower()
    for vm in container_vms.values():
        for cname, container in vm.containers.items():
            if cname.lower() == name_lower:
                return container, vm
    return None, None


def containers_on_vm(container_vms: dict, vm_id: int) -> list:
    """List all containers on a specific VM."""
    vm = container_vms.get(vm_id)
    if not vm:
        return []
    return list(vm.containers.values())


def all_containers(container_vms: dict) -> list:
    """List all containers across all VMs as (Container, ContainerVM) tuples."""
    result = []
    for vm in container_vms.values():
        for container in vm.containers.values():
            result.append((container, vm))
    return result


def container_vm_by_ip(container_vms: dict, ip: str) -> Optional[ContainerVM]:
    """Find a ContainerVM by its IP address."""
    for vm in container_vms.values():
        if vm.ip == ip:
            return vm
    return None
