"""PVE VM-tag discovery and cached access independent of web transport."""

import json
import time

from freq.core import log as logger
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.services import dashboard_state as _dashboard_state
from freq.services.pve_discovery import _get_discovered_node_ips, _get_discovered_nodes

VM_TAGS_INTERVAL = 300

_bg_cache = _dashboard_state.background_cache
_bg_cache_ts = _dashboard_state.background_cache_timestamps
_bg_lock = _dashboard_state.background_cache_lock


def _bg_fetch_vm_tags():
    """Fetch PVE tags for all VMs via batch SSH.

    Queries each PVE node for VM configs, extracts tags.
    Result: {vmid: ["tag1", "tag2", ...]}
    Used for tag-based protection (prod) and categorization (lab, core, etc).
    """
    with _bg_lock:
        last = _bg_cache_ts.get("vm_tags", 0)
    if time.time() - last < VM_TAGS_INTERVAL:
        return

    try:
        cfg = load_config()
        node_ips = _get_discovered_node_ips()
        if not node_ips:
            return

        # Get VM list from cluster resources (one node is enough)
        seed_ip = node_ips[0]
        r = ssh_single(
            host=seed_ip,
            command="pvesh get /cluster/resources --type vm --output-format json",
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )
        if r.returncode != 0 or not r.stdout:
            return

        vms = json.loads(r.stdout)
        # Group VMIDs by node
        node_vmids = {}
        for v in vms:
            if v.get("type") == "qemu":
                node_vmids.setdefault(v.get("node", ""), []).append(v.get("vmid", 0))

        # Build node name to IP mapping
        node_ip_map = {n["name"]: n["ip"] for n in _get_discovered_nodes() if n.get("name") and n.get("ip")}

        # Batch query tags per node
        all_tags = {}
        for node_name, vmids in node_vmids.items():
            nip = node_ip_map.get(node_name)
            if not nip:
                continue
            # Build batch command: for each VMID, print "VMID:<id>" then grep tags.
            # Reading PVE's config file is much faster than repeated CLI config
            # calls and avoids timeout noise on nodes with many VMs.
            cmd_parts = []
            for vid in vmids:
                cmd_parts.append(
                    f"echo VMID:{vid}; "
                    f"grep '^tags' /etc/pve/qemu-server/{int(vid)}.conf 2>/dev/null || true"
                )
            batch_cmd = "; ".join(cmd_parts)
            r = ssh_single(
                host=nip,
                command=batch_cmd,
                key_path=cfg.ssh_key_path,
                command_timeout=30,
                htype="pve",
                use_sudo=True,
                cfg=cfg,
                failure_log_level="warn",
            )
            if r.returncode == 0 and r.stdout:
                cur_vmid = None
                for line in r.stdout.strip().split("\n"):
                    if line.startswith("VMID:"):
                        cur_vmid = int(line[5:])
                    elif cur_vmid is not None and line.startswith("tags:"):
                        raw = line.split(":", 1)[1].strip()
                        # PVE tags are semicolon-separated
                        tags = [t.strip() for t in raw.replace(",", ";").split(";") if t.strip()]
                        all_tags[cur_vmid] = tags

        result = {"tags": all_tags, "fetched_at": time.time()}
    except Exception as e:
        logger.error(f"VM tag fetch failed: {e}")
        result = None

    with _bg_lock:
        _bg_cache["vm_tags"] = result
        _bg_cache_ts["vm_tags"] = time.time()


def get_vm_tags(vmid: int) -> list:
    """Get cached PVE tags for a VMID. Returns list of tag strings."""
    with _bg_lock:
        cache = _bg_cache.get("vm_tags")
    if cache and cache.get("tags"):
        return cache["tags"].get(vmid, [])
    return []


def is_vm_tagged(vmid: int, tag: str) -> bool:
    """Check if a VM has a specific PVE tag (from cache)."""
    return tag in get_vm_tags(vmid)
