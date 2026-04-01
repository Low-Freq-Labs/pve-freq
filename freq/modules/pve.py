"""Proxmox VE cluster operations for FREQ.

Domain: freq vm <list|overview|config|create|clone|destroy|resize|snapshot|migrate|rescue>

Core PVE management: VM listing, creation, cloning, destruction, resizing,
snapshots, and live migration. Operations prefer the PVE REST API (token
auth) and fall back to SSH + pvesh/qm when the API is unreachable.

Replaces: PVE web GUI (limited to one cluster), manual qm/pvesh commands,
          Terraform proxmox provider ($0 but HCL overhead)

Architecture:
    - Dual transport: REST API (urllib, token auth) with SSH fallback
    - PVE API client uses PVEAPIToken header for authentication
    - SSH operations via freq/core/ssh.py with htype="pve" + sudo
    - Safety gates via freq/core/validate.py (protected VMID ranges)

Design decisions:
    - API-first, SSH-fallback. API is faster and structured; SSH works when
      the API is down or no token is configured. Graceful degradation.
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from freq.core import fmt
from freq.core import log as logger
from freq.core import validate
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# PVE timeouts
PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10
PVE_SNAPSHOT_TIMEOUT = 120
PVE_API_PORT = 8006
PVE_API_TIMEOUT = 15


# ── PVE REST API Client ────────────────────────────────────────────────

def _pve_api_call(cfg: FreqConfig, node_ip: str, endpoint: str,
                  method: str = "GET", data: dict = None,
                  timeout: int = PVE_API_TIMEOUT) -> tuple:
    """Call PVE REST API with token auth.

    Returns (parsed_data, success_bool).
    Token auth header: PVEAPIToken=user@realm!tokenname=UUID-SECRET
    """
    if not getattr(cfg, "pve_api_token_id", "") or not getattr(cfg, "pve_api_token_secret", ""):
        return "", False

    url = f"https://{node_ip}:{PVE_API_PORT}/api2/json{endpoint}"
    auth = f"PVEAPIToken={cfg.pve_api_token_id}={cfg.pve_api_token_secret}"

    headers = {"Authorization": auth, "Accept": "application/json"}

    req_data = None
    if data:
        req_data = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    ctx = ssl.create_default_context()
    if not getattr(cfg, "pve_api_verify_ssl", False):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = json.loads(resp.read().decode())
            return body.get("data", body), True
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError, TimeoutError) as e:
        logger.debug(f"PVE API call failed ({node_ip}{endpoint}): {e}")
        return str(e), False


def _pve_call(cfg: FreqConfig, node_ip: str,
              api_endpoint: str, ssh_command: str,
              timeout: int = PVE_CMD_TIMEOUT,
              method: str = "GET", data: dict = None) -> tuple:
    """Try PVE REST API first, fall back to SSH.

    Returns (result, success_bool). Result is parsed JSON from API
    or stdout string from SSH.
    """
    if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
        result, ok = _pve_api_call(cfg, node_ip, api_endpoint,
                                   method=method, data=data,
                                   timeout=min(timeout, PVE_API_TIMEOUT))
        if ok:
            return result, True

    # Fallback to SSH
    return _pve_cmd(cfg, node_ip, ssh_command, timeout=timeout)


# ── SSH Foundation ──────────────────────────────────────────────────────

def _pve_cmd(cfg: FreqConfig, node_ip: str, command: str, timeout: int = PVE_CMD_TIMEOUT) -> tuple:
    """Execute a command on a PVE node via SSH + sudo.

    Returns (stdout, success). This is the foundation — every PVE
    operation goes through here.
    """
    r = ssh_run(
        host=node_ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve",
        use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def _find_reachable_node(cfg: FreqConfig) -> str:
    """Find the first reachable PVE node. Tries API first, then SSH."""
    for ip in cfg.pve_nodes:
        # Try API first if token is configured
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            _, ok = _pve_api_call(cfg, ip, "/version", timeout=PVE_QUICK_TIMEOUT)
            if ok:
                return ip
        # Fall back to SSH
        r = ssh_run(
            host=ip, command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_QUICK_TIMEOUT, htype="pve", use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def cmd_list(cfg: FreqConfig, pack, args) -> int:
    """List all VMs across the PVE cluster."""
    fmt.header("VM Inventory")
    fmt.blank()

    if not cfg.pve_nodes:
        fmt.line(f"{fmt.C.YELLOW}No PVE nodes configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Find a reachable node
    fmt.step_start("Connecting to PVE cluster")
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.line(f"{fmt.C.GRAY}Configured nodes: {', '.join(cfg.pve_nodes)}{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Check SSH access: ssh {cfg.ssh_service_account}@<node-ip>{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Get cluster VM list (API-first with SSH fallback)
    result, ok = _pve_call(cfg, node_ip,
                           api_endpoint="/cluster/resources?type=vm",
                           ssh_command="pvesh get /cluster/resources --type vm --output-format json")
    if not ok or not result:
        fmt.step_fail("Failed to query cluster resources")
        fmt.blank()
        fmt.footer()
        return 1

    try:
        vms = result if isinstance(result, list) else json.loads(result)
    except (json.JSONDecodeError, TypeError):
        fmt.step_fail("Invalid JSON from PVE API")
        fmt.blank()
        fmt.footer()
        return 1

    # Filter by args
    node_filter = getattr(args, "node", None)
    status_filter = getattr(args, "status", None)

    if node_filter:
        vms = [v for v in vms if v.get("node", "") == node_filter]
    if status_filter:
        vms = [v for v in vms if v.get("status", "") == status_filter.lower()]

    # Sort by node, then VMID
    vms.sort(key=lambda v: (v.get("node", ""), v.get("vmid", 0)))

    fmt.step_ok(f"Found {len(vms)} VMs across cluster")
    fmt.blank()

    if not vms:
        fmt.line(f"{fmt.C.YELLOW}No VMs found.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Table
    fmt.table_header(
        ("VMID", 6),
        ("NAME", 20),
        ("NODE", 8),
        ("STATUS", 10),
        ("CPU", 4),
        ("RAM", 8),
        ("TYPE", 6),
    )

    for v in vms:
        vmid = v.get("vmid", "?")
        name = v.get("name", "—")[:20]
        node = v.get("node", "?")
        status = v.get("status", "?")
        cpus = str(v.get("maxcpu", "?"))
        ram_bytes = v.get("maxmem", 0)
        ram_mb = ram_bytes // (1024 * 1024) if ram_bytes else 0
        ram_str = f"{ram_mb}MB" if ram_mb else "?"
        vm_type = v.get("type", "?")

        # Color status
        if status == "running":
            status_badge = fmt.badge("running")
        elif status == "stopped":
            status_badge = fmt.badge("down")
        else:
            status_badge = fmt.badge(status)

        # Protected VMID indicator — PVE tags + static fallback
        vm_tags = None
        try:
            from freq.modules.serve import get_vm_tags
            vm_tags = get_vm_tags(vmid)
        except ImportError:
            pass
        protected = ""
        if validate.is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges,
                                      vm_tags=vm_tags):
            protected = f" {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}"

        fmt.table_row(
            (f"{vmid}{protected}", 6),
            (name, 20),
            (node, 8),
            (status_badge, 10),
            (cpus, 4),
            (ram_str, 8),
            (vm_type, 6),
        )

    fmt.blank()

    # Summary
    running = sum(1 for v in vms if v.get("status") == "running")
    stopped = sum(1 for v in vms if v.get("status") == "stopped")
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{running}{fmt.C.RESET} running  "
        f"{fmt.C.RED}{stopped}{fmt.C.RESET} stopped  "
        f"({len(vms)} total)"
    )
    fmt.blank()
    fmt.footer()

    return 0


def cmd_vm_overview(cfg: FreqConfig, pack, args) -> int:
    """VM inventory across cluster — alias for list with extra detail."""
    return cmd_list(cfg, pack, args)


def cmd_vmconfig(cfg: FreqConfig, pack, args) -> int:
    """View VM configuration."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq vmconfig <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"VM Config: {vmid}")
    fmt.blank()

    # Find which node has this VM
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    # Get VM config
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    if not ok:
        fmt.line(f"{fmt.C.RED}VM {vmid} not found or not accessible.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Parse and display config
    for line in stdout.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            fmt.line(f"  {fmt.C.CYAN}{key:>20}{fmt.C.RESET}: {value}")
        elif line.strip():
            fmt.line(f"  {line}")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_snapshot(cfg: FreqConfig, pack, args) -> int:
    """Snapshot management: create, list, or delete snapshots."""
    target = getattr(args, "target", None)
    action = getattr(args, "snap_action", None) or "create"

    # Handle subactions
    if action == "list":
        return cmd_snapshot_list(cfg, pack, args)
    elif action == "delete":
        return cmd_snapshot_delete(cfg, pack, args)

    # Default: create
    if not target:
        fmt.error("Usage: freq snapshot <vmid> [--name <snap_name>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    snap_name = getattr(args, "name", None) or f"freq-snap-{vmid}"

    fmt.header(f"Snapshot VM {vmid}")
    fmt.blank()

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.step_start(f"Creating snapshot '{snap_name}' for VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm snapshot {vmid} {snap_name} --description 'Created by FREQ'", timeout=PVE_SNAPSHOT_TIMEOUT)

    if ok:
        fmt.step_ok(f"Snapshot '{snap_name}' created for VM {vmid}")
    else:
        fmt.step_fail(f"Snapshot failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_snapshot_list(cfg: FreqConfig, pack, args) -> int:
    """List all snapshots for a VM."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq snapshot list <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"Snapshots: VM {vmid}")
    fmt.blank()

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.step_start(f"Querying snapshots for VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid}", timeout=PVE_CMD_TIMEOUT)

    if not ok:
        fmt.step_fail(f"Failed to list snapshots: {stdout}")
        fmt.blank()
        fmt.footer()
        return 1

    # Parse snapshot output
    snaps = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            name = parts[0].replace("`-", "").replace("->", "").strip()
            if name and name != "current":
                snaps.append(name)

    fmt.step_ok(f"Found {len(snaps)} snapshot(s)")
    fmt.blank()

    if not snaps:
        fmt.line(f"  {fmt.C.YELLOW}No snapshots found for VM {vmid}.{fmt.C.RESET}")
    else:
        fmt.table_header(("SNAPSHOT", 30), ("VM", 8))
        for snap in snaps:
            fmt.table_row((snap, 30), (str(vmid), 8))

    fmt.blank()
    fmt.footer()
    return 0


def cmd_snapshot_delete(cfg: FreqConfig, pack, args) -> int:
    """Delete a snapshot from a VM."""
    target = getattr(args, "target", None)
    snap_name = getattr(args, "name", None)

    if not target or not snap_name:
        fmt.error("Usage: freq snapshot delete <vmid> --name <snapshot_name>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', snap_name):
        fmt.error(f"Invalid snapshot name: {snap_name} (alphanumeric, hyphens, underscores only)")
        return 1

    fmt.header(f"Delete Snapshot: VM {vmid}")
    fmt.blank()

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    # Confirm unless --yes
    if not getattr(args, "yes", False):
        fmt.line(f"  {fmt.C.YELLOW}Delete snapshot '{snap_name}' from VM {vmid}?{fmt.C.RESET}")
        try:
            confirm = input(f"  {fmt.C.YELLOW}Confirm [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    fmt.step_start(f"Deleting snapshot '{snap_name}' from VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm delsnapshot {vmid} {snap_name}", timeout=PVE_SNAPSHOT_TIMEOUT)

    if ok:
        fmt.step_ok(f"Snapshot '{snap_name}' deleted from VM {vmid}")
    else:
        fmt.step_fail(f"Delete failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_power(cfg: FreqConfig, pack, args) -> int:
    """VM power control: start, stop, reboot, shutdown, status."""
    action = getattr(args, "action", None)
    target = getattr(args, "target", None)

    if not action or not target:
        fmt.error("Usage: freq power <start|stop|reboot|shutdown|status> <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    # Safety check for destructive actions — PVE tags + static fallback
    if action in ("stop", "reboot", "shutdown"):
        pve_tags = None
        try:
            from freq.modules.serve import get_vm_tags
            pve_tags = get_vm_tags(vmid)
        except ImportError:
            pass
        if validate.is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges,
                                      vm_tags=pve_tags):
            fmt.error(f"VM {vmid} is PROTECTED. Cannot {action}.")
            return 1

    fmt.header(f"VM Power: {action.upper()} {vmid}")
    fmt.blank()

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    ssh_cmds = {
        "start": f"qm start {vmid}",
        "stop": f"qm stop {vmid}",
        "reboot": f"qm reset {vmid}",
        "shutdown": f"qm shutdown {vmid}",
        "status": f"qm status {vmid}",
    }
    # API endpoints need the node name — resolve via cluster resources
    api_actions = {
        "start": ("start", "POST"),
        "stop": ("stop", "POST"),
        "reboot": ("reset", "POST"),
        "shutdown": ("shutdown", "POST"),
        "status": ("current", "GET"),
    }
    ssh_cmd = ssh_cmds.get(action)
    if not ssh_cmd:
        fmt.error(f"Unknown action: {action}. Use start|stop|reboot|shutdown|status")
        return 1

    fmt.step_start(f"Executing: {action} VM {vmid}")

    # Try API first: need to resolve which node hosts this VM
    ok = False
    result = ""
    if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
        api_action, api_method = api_actions[action]
        # Find the VM's node via cluster resources
        res_data, res_ok = _pve_api_call(cfg, node_ip,
                                         f"/cluster/resources?type=vm",
                                         timeout=PVE_QUICK_TIMEOUT)
        if res_ok and isinstance(res_data, list):
            vm_entry = next((v for v in res_data if v.get("vmid") == vmid), None)
            if vm_entry:
                node_name = vm_entry.get("node", "")
                if node_name:
                    result, ok = _pve_api_call(
                        cfg, node_ip,
                        f"/nodes/{node_name}/qemu/{vmid}/status/{api_action}",
                        method=api_method, timeout=60)

    # Fallback to SSH
    if not ok:
        result, ok = _pve_cmd(cfg, node_ip, ssh_cmd, timeout=60)

    if ok:
        if action == "status":
            status_text = result
            if isinstance(result, dict):
                status_text = result.get("status", str(result))
            elif isinstance(result, str):
                status_text = result.strip()
            fmt.step_ok(f"VM {vmid}: {status_text}")
        else:
            fmt.step_ok(f"VM {vmid} — {action} successful")
    else:
        fmt.step_fail(f"{action} failed: {result}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1
