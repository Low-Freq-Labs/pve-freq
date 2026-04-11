"""Docker/container domain API handlers -- /api/containers/*, /api/stack/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for container registry, compose management, and stacks.
Why:   Decouples Docker logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import os

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single, result_for
from freq.modules.serve import (
    _parse_query_flat,
    _check_session_role,
    _resolve_container_vm_ip,
    _write_containers_toml,
)


# -- Handlers ----------------------------------------------------------------


def handle_containers_registry(handler):
    """GET /api/containers/registry -- list all registered containers."""
    cfg = load_config()
    entries = []
    for vm in sorted(cfg.container_vms.values(), key=lambda v: v.vm_id):
        for cname, c in vm.containers.items():
            entries.append(
                {
                    "name": cname,
                    "vm_id": vm.vm_id,
                    "vm_label": vm.label,
                    "vm_ip": vm.ip,
                    "port": c.port,
                    "api_path": c.api_path,
                }
            )
    json_response(handler, {
        "containers": entries,
        "registry_configured": bool(cfg.container_vms),
    })


def handle_containers_rescan(handler):
    """POST /api/containers/rescan -- SSH into docker VMs, discover containers."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    discovered = {}
    for vm in cfg.container_vms.values():
        r = ssh_single(
            host=_resolve_container_vm_ip(vm),
            command="docker ps -a --format '{{.Names}}' 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="docker",
            use_sudo=False,
            cfg=cfg,
        )
        names = []
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().split("\n"):
                n = line.strip()
                if n:
                    names.append(n)
        discovered[vm.vm_id] = names

    registered = {}
    for vm in cfg.container_vms.values():
        for cname in vm.containers:
            registered[f"{vm.vm_id}:{cname}"] = {"name": cname, "vm_id": vm.vm_id, "vm_label": vm.label}

    stale = []
    for key, info in registered.items():
        vm_id = info["vm_id"]
        cname = info["name"]
        vm_containers = discovered.get(vm_id, [])
        found = any(cname.lower() == dc.lower() for dc in vm_containers)
        if not found:
            stale.append(info)

    new_found = []
    for vm_id, names in discovered.items():
        vm = cfg.container_vms.get(vm_id)
        if not vm:
            continue
        for dc in names:
            already = any(dc.lower() == cname.lower() for cname in vm.containers)
            if not already:
                new_found.append({"name": dc, "vm_id": vm_id, "vm_label": vm.label})

    json_response(
        handler,
        {
            "discovered": {str(k): v for k, v in discovered.items()},
            "stale": stale,
            "new": new_found,
            "vm_count": len(cfg.container_vms),
        },
    )


def handle_containers_delete(handler):
    """POST /api/containers/delete -- remove a container from the registry."""
    if require_post(handler, "Container delete"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = _parse_query_flat(handler.path)
    name = query.get("name", "")
    try:
        vm_id = int(query.get("vm_id", "0"))
    except (ValueError, TypeError):
        json_response(handler, {"error": "Invalid vm_id"}, 400)
        return
    if not name or not vm_id:
        json_response(handler, {"error": "name and vm_id required"}, 400)
        return

    cfg = load_config()
    toml_path = os.path.join(cfg.conf_dir, "containers.toml")
    vm = cfg.container_vms.get(vm_id)
    if not vm:
        json_response(handler, {"error": f"VM {vm_id} not in registry"}, 404)
        return
    if name not in vm.containers:
        json_response(handler, {"error": f"Container {name} not found on VM {vm_id}"}, 404)
        return

    del vm.containers[name]
    _write_containers_toml(toml_path, cfg.container_vms)
    json_response(handler, {"ok": True, "deleted": name, "vm_id": vm_id})


def handle_containers_add(handler):
    """POST /api/containers/add -- add a container to the registry."""
    if require_post(handler, "Container add"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = _parse_query_flat(handler.path)
    name = query.get("name", "").strip()
    try:
        vm_id = int(query.get("vm_id", "0"))
    except (ValueError, TypeError):
        json_response(handler, {"error": "Invalid vm_id"}, 400)
        return
    try:
        port = int(query.get("port", "0"))
    except (ValueError, TypeError):
        port = 0
    if not name or not vm_id:
        json_response(handler, {"error": "name and vm_id required"}, 400)
        return

    cfg = load_config()
    toml_path = os.path.join(cfg.conf_dir, "containers.toml")
    vm = cfg.container_vms.get(vm_id)
    if not vm:
        json_response(handler, {"error": f"VM {vm_id} not in registry"}, 404)
        return
    if name in vm.containers:
        json_response(handler, {"error": f"Container {name} already registered on VM {vm_id}"}, 409)
        return

    from freq.core.config import Container

    vm.containers[name] = Container(name=name, vm_id=vm_id, port=port)
    _write_containers_toml(toml_path, cfg.container_vms)
    json_response(handler, {"ok": True, "added": name, "vm_id": vm_id})


def handle_containers_edit(handler):
    """POST /api/containers/edit -- edit a container in the registry."""
    if require_post(handler, "Container edit"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = _parse_query_flat(handler.path)
    name = query.get("name", "").strip()
    try:
        old_vm_id = int(query.get("old_vm_id", "0"))
    except (ValueError, TypeError):
        json_response(handler, {"error": "Invalid old_vm_id"}, 400)
        return
    try:
        new_vm_id = int(query.get("new_vm_id", "0"))
    except (ValueError, TypeError):
        json_response(handler, {"error": "Invalid new_vm_id"}, 400)
        return
    try:
        port = int(query.get("port", "0"))
    except (ValueError, TypeError):
        port = 0
    api_path = query.get("api_path", "")
    if not name or not old_vm_id or not new_vm_id:
        json_response(handler, {"error": "name, old_vm_id, new_vm_id required"}, 400)
        return

    cfg = load_config()
    toml_path = os.path.join(cfg.conf_dir, "containers.toml")
    old_vm = cfg.container_vms.get(old_vm_id)
    if not old_vm or name not in old_vm.containers:
        json_response(handler, {"error": f"Container {name} not found on VM {old_vm_id}"}, 404)
        return

    if old_vm_id == new_vm_id:
        c = old_vm.containers[name]
        c.port = port
        c.api_path = api_path
    else:
        new_vm = cfg.container_vms.get(new_vm_id)
        if not new_vm:
            json_response(handler, {"error": f"VM {new_vm_id} not in registry"}, 404)
            return
        if name in new_vm.containers:
            json_response(handler, {"error": f"Container {name} already exists on VM {new_vm_id}"}, 409)
            return
        from freq.core.config import Container

        new_vm.containers[name] = Container(
            name=name,
            vm_id=new_vm_id,
            port=port,
            api_path=api_path,
        )
        del old_vm.containers[name]

    _write_containers_toml(toml_path, cfg.container_vms)
    json_response(handler, {"ok": True, "name": name, "vm_id": new_vm_id})


def handle_containers_compose_up(handler):
    """POST /api/containers/compose-up -- start a Docker Compose stack."""
    if require_post(handler, "Docker Compose up"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    query = _parse_query_flat(handler.path)
    vm_id = int(query.get("vm_id", "0"))

    vm = cfg.container_vms.get(vm_id)
    if not vm:
        json_response(handler, {"error": f"VM {vm_id} not in container registry"}, 404)
        return

    compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
    host_ip = _resolve_container_vm_ip(vm)
    cmd = f"cd {compose_path} && docker compose up -d"
    r = ssh_single(
        host=host_ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=120,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    json_response(
        handler,
        {
            "ok": r.returncode == 0,
            "vm_id": vm_id,
            "vm": vm.label,
            "output": (r.stdout or "")[:1000],
            "error": (r.stderr or "")[:500] if r.returncode != 0 else "",
        },
    )


def handle_containers_compose_down(handler):
    """POST /api/containers/compose-down -- stop a Docker Compose stack."""
    if require_post(handler, "Docker Compose down"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    query = _parse_query_flat(handler.path)
    vm_id = int(query.get("vm_id", "0"))

    vm = cfg.container_vms.get(vm_id)
    if not vm:
        json_response(handler, {"error": f"VM {vm_id} not in container registry"}, 404)
        return

    compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
    host_ip = _resolve_container_vm_ip(vm)
    cmd = f"cd {compose_path} && docker compose down"
    r = ssh_single(
        host=host_ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=120,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    json_response(
        handler,
        {
            "ok": r.returncode == 0,
            "vm_id": vm_id,
            "vm": vm.label,
            "output": (r.stdout or "")[:1000],
            "error": (r.stderr or "")[:500] if r.returncode != 0 else "",
        },
    )


def handle_containers_compose_view(handler):
    """GET /api/containers/compose-view -- read docker-compose.yml for a VM."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    query = _parse_query_flat(handler.path)
    vm_id = int(query.get("vm_id", "0"))

    vm = cfg.container_vms.get(vm_id)
    if not vm:
        json_response(handler, {"error": f"VM {vm_id} not in container registry"}, 404)
        return

    compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
    host_ip = _resolve_container_vm_ip(vm)
    cmd = f"cat {compose_path}/docker-compose.yml 2>/dev/null || cat {compose_path}/compose.yml 2>/dev/null"
    r = ssh_single(
        host=host_ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    if r.returncode == 0 and r.stdout:
        json_response(
            handler,
            {
                "ok": True,
                "vm_id": vm_id,
                "vm": vm.label,
                "content": r.stdout[:10000],
            },
        )
    else:
        json_response(
            handler,
            {
                "ok": False,
                "vm_id": vm_id,
                "error": "Compose file not found or not readable",
            },
        )


def handle_stack_status(handler):
    """GET /api/stack/status -- live Docker Compose stack status across fleet."""
    import json as _json

    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"stacks": [], "total": 0})
        return

    command = "docker compose ls --format json 2>/dev/null || docker-compose ls --format json 2>/dev/null || echo '[]'"
    from freq.core.ssh import run_many as ssh_run_many, result_for

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    stacks = []
    unreachable = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            unreachable.append({"label": h.label, "ip": h.ip, "error": r.stderr.strip()[:120] if r else "no response"})
            continue
        try:
            host_stacks = _json.loads(r.stdout.strip())
        except (ValueError, _json.JSONDecodeError) as e:
            logger.debug(f"api_docker: failed to parse stack status from {h.label}: {e}")
            continue
        for stack in host_stacks:
            status_raw = stack.get("Status", "unknown")
            svc_match = status_raw.split("(")
            services = svc_match[1].rstrip(")") if len(svc_match) > 1 else "?"
            stacks.append(
                {
                    "host": h.label,
                    "name": stack.get("Name", "unknown"),
                    "status": status_raw.split("(")[0].strip() if "(" in status_raw else status_raw,
                    "services": services,
                    "config": stack.get("ConfigFiles", ""),
                }
            )

    json_response(handler, {"stacks": stacks, "total": len(stacks), "unreachable": unreachable, "hosts_queried": len(hosts), "hosts_failed": len(unreachable)})


def handle_stack_health(handler):
    """GET /api/stack/health -- live container health across fleet."""
    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"containers": [], "healthy": 0, "unhealthy": 0})
        return

    command = "docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null || echo ''"
    from freq.core.ssh import run_many as ssh_run_many, result_for

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    containers = []
    healthy = 0
    unhealthy = 0
    unreachable_health = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0 or not r.stdout.strip():
            unreachable_health.append({"label": h.label, "ip": h.ip, "error": r.stderr.strip()[:120] if r and r.stderr else "no response"})
            continue
        for line in r.stdout.strip().split("\n"):
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            name, status, image = parts
            is_healthy = "Up" in status and "unhealthy" not in status.lower()
            if is_healthy:
                healthy += 1
            else:
                unhealthy += 1
            containers.append(
                {
                    "host": h.label,
                    "name": name,
                    "status": status,
                    "image": image,
                    "healthy": is_healthy,
                }
            )

    json_response(
        handler,
        {
            "containers": containers,
            "total": len(containers),
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unreachable": unreachable_health,
            "hosts_queried": len(hosts),
            "hosts_failed": len(unreachable_health),
        },
    )


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register Docker/container API routes into the master route table."""
    routes["/api/containers/registry"] = handle_containers_registry
    routes["/api/containers/rescan"] = handle_containers_rescan
    routes["/api/containers/delete"] = handle_containers_delete
    routes["/api/containers/add"] = handle_containers_add
    routes["/api/containers/edit"] = handle_containers_edit
    routes["/api/containers/compose-up"] = handle_containers_compose_up
    routes["/api/containers/compose-down"] = handle_containers_compose_down
    routes["/api/containers/compose-view"] = handle_containers_compose_view
    routes["/api/stack/status"] = handle_stack_status
    routes["/api/stack/health"] = handle_stack_health
