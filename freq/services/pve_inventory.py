"""Cluster-wide PVE VM inventory and dashboard enrichment."""

import json

from freq.services.pve_discovery import _get_discovered_node_ips
from freq.services.pve_tags import get_vm_tags
from freq.services.pve_transport import _pve_call
from freq.services.vm_visibility import _dashboard_vm_scope, _dashboard_vm_visible


def _get_fleet_vms(cfg):
    """Fetch cluster VMs enriched with fleet-boundary dashboard truth."""
    fb = cfg.fleet_boundaries
    dashboard_scope = _dashboard_vm_scope(cfg)
    vm_list = []
    for node_ip in _get_discovered_node_ips():
        result, ok = _pve_call(
            cfg,
            node_ip,
            api_endpoint="/cluster/resources?type=vm",
            ssh_command="pvesh get /cluster/resources --type vm --output-format json",
            timeout=15,
        )
        if ok and result:
            try:
                vms = result if isinstance(result, list) else json.loads(result)
                for vm in vms:
                    vmid = vm.get("vmid", 0)
                    template_flag = vm.get("template", 0)
                    is_template = bool(template_flag) or 9000 <= int(vmid or 0) < 10000
                    if not is_template and not _dashboard_vm_visible(vm, dashboard_scope):
                        continue
                    if is_template:
                        cat_name, tier = "templates", "protected"
                    else:
                        cat_name, tier = fb.categorize(vmid)
                    tags = get_vm_tags(vmid)
                    vm_name = str(vm.get("name", "") or "").strip()
                    if not vm_name and vmid and vm.get("node"):
                        config_result, config_ok = _pve_call(
                            cfg,
                            node_ip,
                            api_endpoint=f"/nodes/{vm.get('node')}/qemu/{vmid}/config",
                            ssh_command=(
                                f"pvesh get /nodes/{vm.get('node')}/qemu/{vmid}/config "
                                "--output-format json"
                            ),
                            timeout=10,
                        )
                        if config_ok and config_result:
                            try:
                                vm_config = (
                                    config_result
                                    if isinstance(config_result, dict)
                                    else json.loads(config_result)
                                )
                                vm_name = str(vm_config.get("name", "") or "").strip()
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                vm_name = ""
                    if not vm_name:
                        vm_name = f"vm-{vmid}"
                    cpu_real = vm.get("cpu", 0)
                    cpu_pct = (
                        round(cpu_real * 100, 1)
                        if isinstance(cpu_real, (int, float))
                        else 0
                    )
                    mem_used = vm.get("mem", 0) or 0
                    mem_max = vm.get("maxmem", 0) or 0
                    vm_list.append(
                        {
                            "vmid": vmid,
                            "name": vm_name,
                            "node": vm.get("node", ""),
                            "status": vm.get("status", ""),
                            "cpu": vm.get("maxcpu", 0),
                            "cpu_pct": cpu_pct,
                            "ram_mb": mem_max // (1024 * 1024) if mem_max else 0,
                            "ram_used_mb": mem_used // (1024 * 1024) if mem_used else 0,
                            "ram_pct": (
                                min(round(mem_used / mem_max * 100, 1), 100.0)
                                if mem_max
                                else 0
                            ),
                            "type": vm.get("type", ""),
                            "category": cat_name,
                            "tier": tier,
                            "tags": tags,
                            "allowed_actions": fb.allowed_actions(vmid),
                            "is_prod": fb.is_prod(vmid) or "prod" in tags,
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        break
    return vm_list
