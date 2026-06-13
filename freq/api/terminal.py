"""Terminal API — in-browser SSH sessions via websocket + PTY.

Provides live interactive terminals for VMs, LXC containers, and PVE nodes
directly in the dashboard using xterm.js on the client side.

Architecture:
    Browser (xterm.js) ←→ WebSocket ←→ PTY ←→ SSH process

    1. Client POSTs /api/terminal/open to create a session
    2. Server spawns SSH in a PTY, stores session
    3. Client connects to /api/terminal/ws?session=<id> for websocket
    4. Server bridges PTY fd ↔ websocket frames using select()
    5. Cleanup on disconnect or timeout

Terminal types:
    - vm:   Resolve a VMID to a guest IP, then SSH as service account
    - host: SSH directly to a host/device IP as service account
    - ct:   SSH to PVE node, then pct exec <ctid> -- bash
    - node: SSH directly to PVE node (service-account@<ip>)
"""

import base64
import hashlib
import json
import os
import pty
import re
import secrets
import select
import signal
import shlex
import struct
import subprocess
import threading
import time

from freq.core import log as logger
from freq.api.helpers import require_post, json_response, get_params
from freq.api.auth import current_user
from freq.core.config import load_config
from freq.core.device_credentials import resolve_staged_device_ssh_auth
from freq.core.ssh import _build_ssh_cmd, run as ssh_single
from freq.modules import serve as serve_module
from freq.modules.serve import _check_session_role


# ── Session Store ──────────────────────────────────────────────────────

_sessions = {}
_sessions_lock = threading.Lock()
_SESSION_TIMEOUT = 900  # 15 minutes idle timeout
_MAX_SESSIONS = 20
IDRAC_TERMINAL_SPAWN_GAP_SECONDS = 10.0


def _wait_for_idrac_terminal_spawn_window() -> None:
    """Throttle iDRAC terminal spawns after live BMC reads."""
    with serve_module.IDRAC_SESSION_LOCK:
        since = time.monotonic() - serve_module._idrac_last_session_at
        if since < IDRAC_TERMINAL_SPAWN_GAP_SECONDS:
            time.sleep(IDRAC_TERMINAL_SPAWN_GAP_SECONDS - since)
        serve_module._idrac_last_session_at = time.monotonic()


def _cleanup_stale():
    """Remove sessions idle > timeout."""
    now = time.time()
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items() if now - s["last_active"] > _SESSION_TIMEOUT]
        for sid in stale:
            _kill_session(sid)


def _kill_session(sid):
    """Kill a session's SSH process and close PTY. Must hold _sessions_lock."""
    s = _sessions.pop(sid, None)
    if not s:
        return
    try:
        if s.get("kill_pgrp"):
            os.killpg(s["pid"], signal.SIGTERM)
        else:
            os.kill(s["pid"], signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        os.close(s["fd"])
    except OSError:
        pass


# ── Session Creation ───────────────────────────────────────────────────


def _resolve_pve_node_ip(cfg, node_ref: str) -> str:
    """Resolve a PVE node name/IP using the live dashboard discovery cache."""
    if not node_ref:
        return ""
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", node_ref):
        return node_ref
    try:
        from freq.modules.serve import _get_discovered_nodes

        for node in _get_discovered_nodes():
            if node.get("name") == node_ref or node.get("ip") == node_ref:
                return node.get("ip", "")
    except Exception as e:
        logger.warn(f"terminal: live node discovery lookup failed for {node_ref}: {e}")

    for idx, name in enumerate(getattr(cfg, "pve_node_names", []) or []):
        if name == node_ref and idx < len(getattr(cfg, "pve_nodes", []) or []):
            return cfg.pve_nodes[idx]

    fb = getattr(cfg, "fleet_boundaries", None)
    if fb:
        for pve_node in getattr(fb, "pve_nodes", {}).values():
            if getattr(pve_node, "name", "") == node_ref or getattr(pve_node, "ip", "") == node_ref:
                return getattr(pve_node, "ip", "")
    return ""


def _find_live_vm_node_ip(cfg, vmid: int, node_ref: str = "") -> tuple[str, str]:
    """Return (node_ip, node_name) for a VM using live cluster inventory."""
    node_ip = _resolve_pve_node_ip(cfg, node_ref)
    if node_ip:
        return node_ip, node_ref

    try:
        from freq.modules.serve import _get_fleet_vms

        vm = next((v for v in _get_fleet_vms(cfg) if int(v.get("vmid", 0) or 0) == vmid), None)
        if vm:
            node_name = vm.get("node", "")
            node_ip = _resolve_pve_node_ip(cfg, node_name)
            if node_ip:
                return node_ip, node_name
    except Exception as e:
        logger.warn(f"terminal: live VM ownership lookup failed for VMID {vmid}: {e}")

    try:
        from freq.modules.pve import _find_vm_node

        node_ip = _find_vm_node(cfg, vmid, "")
        if node_ip:
            return node_ip, node_ref
    except Exception as e:
        logger.warn(f"terminal: fallback VM node lookup failed for VMID {vmid}: {e}")
    return "", ""


def _guest_agent_network_json(cfg, vmid: int, node_ip: str, node_name: str) -> tuple[str, bool, str]:
    """Fetch guest-agent interface JSON for a VM, preferring the PVE API."""
    if node_name:
        try:
            from freq.modules.pve import _pve_api_call

            result, ok = _pve_api_call(
                cfg,
                node_ip,
                f"/nodes/{node_name}/qemu/{vmid}/agent/network-get-interfaces",
                timeout=10,
            )
            if ok:
                return json.dumps(result), True, "pve_api"
        except Exception as e:
            logger.warn(f"terminal: PVE API guest-agent lookup failed for VMID {vmid}: {e}")

    try:
        from freq.modules.pve import _pve_cmd

        out, ok = _pve_cmd(
            cfg,
            node_ip,
            f"qm agent {vmid} network-get-interfaces 2>/dev/null",
            timeout=10,
        )
        return out, ok, "pve_ssh"
    except Exception as e:
        logger.warn(f"terminal: SSH guest-agent lookup failed for VMID {vmid}: {e}")
        return str(e), False, "pve_ssh"


def _extract_guest_ipv4(raw: str) -> str:
    """Extract the first usable IPv4 address from QEMU guest-agent JSON."""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return ""
    interfaces = data.get("result", data) if isinstance(data, dict) else data
    if not isinstance(interfaces, list):
        return ""
    for iface in interfaces:
        if not isinstance(iface, dict) or iface.get("name") == "lo":
            continue
        for addr in iface.get("ip-addresses", []) or []:
            if not isinstance(addr, dict) or addr.get("ip-address-type") != "ipv4":
                continue
            ip = addr.get("ip-address", "")
            if ip and not ip.startswith("127."):
                return ip
    return ""


def _terminal_ssh_auth(cfg, htype: str) -> dict:
    """Return the SSH identity used for an interactive terminal.

    This deliberately mirrors the read APIs instead of blindly using staged
    root-only device credentials. The dashboard process runs as the deployed
    service account, so a terminal command must use files that account can
    actually read.
    """
    htype = (htype or "linux").lower()
    if htype in ("pfsense", "idrac", "switch", "truenas"):
        return resolve_staged_device_ssh_auth(cfg, htype)

    key_path = getattr(cfg, "ssh_key_path", "")
    if htype in ("idrac", "switch"):
        key_path = getattr(cfg, "ssh_rsa_key_path", "") or key_path

    password_file = None
    if htype == "switch":
        password_file = getattr(cfg, "legacy_password_file", "") or None

    return {
        "user": getattr(cfg, "ssh_service_account", "") or "freq-admin",
        "key_path": key_path,
        "password_file": password_file,
        "sudo_password_file": False,
        "local_user": None,
    }


def _terminal_preflight(cfg, htype: str, host: str, auth: dict) -> tuple[bool, str]:
    """Preflight only cases where a spawned terminal would be misleading."""
    if htype != "truenas":
        return True, ""
    r = ssh_single(
        host=host,
        command="true",
        user=auth["user"],
        key_path=auth["key_path"],
        connect_timeout=4,
        command_timeout=6,
        htype=htype,
        use_sudo=False,
        local_user=auth.get("local_user") or None,
        password_file=auth.get("password_file"),
        sudo_password_file=auth.get("sudo_password_file", False),
        cfg=cfg,
        failure_log_level="warn",
    )
    if r.returncode == 0:
        return True, ""
    evidence = (r.stderr or r.stdout or "").strip()
    low = evidence.lower()
    if "permission denied" in low or "publickey" in low:
        return False, "Terminal unavailable: TrueNAS SSH credentials were rejected. TrueNAS reads are API-backed; stage working SSH credentials to open an interactive shell."
    return False, f"Terminal unavailable: TrueNAS SSH preflight failed ({evidence[:180] or 'no output'})."


def handle_terminal_open(handler):
    """POST /api/terminal/open — create a new terminal session."""
    if require_post(handler, "Terminal open"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    _cleanup_stale()

    with _sessions_lock:
        if len(_sessions) >= _MAX_SESSIONS:
            json_response(handler, {"error": "Too many active sessions"}, 429)
            return

    cfg = load_config()
    params = get_params(handler)
    term_type = params.get("type", ["vm"])[0]  # vm, host, ct, node
    target = params.get("target", [""])[0]  # IP or CTID
    node = params.get("node", [""])[0]  # PVE node IP (for ct type)
    cols = int(params.get("cols", ["120"])[0])
    rows = int(params.get("rows", ["30"])[0])

    if not target:
        json_response(handler, {"error": "target parameter required"}, 400)
        return

    # Validate target — must be IP or numeric VMID/CTID, no shell metacharacters
    if not re.match(r"^[a-zA-Z0-9._:-]+$", target):
        json_response(handler, {"error": "Invalid target (alphanumeric, dots, colons, hyphens only)"}, 400)
        return
    if node and not re.match(r"^[a-zA-Z0-9._:-]+$", node):
        json_response(handler, {"error": "Invalid node parameter"}, 400)
        return

    # Resolve target IP for VMs (target can be IP or VMID)
    resolved_ip = target
    if term_type == "vm" and target.isdigit():
        vmid = int(target)

        # 1. Host registry, when populated. This is a convenience path, not
        # the source of truth for dashboard-listed VMs.
        for h in cfg.hosts:
            if getattr(h, "vmid", 0) == vmid:
                resolved_ip = h.ip
                break
        else:
            # 2. Live PVE ownership + guest agent. A VM card can render from
            # PVE inventory even when hosts.toml is empty; terminal must use
            # that same truth instead of telling the operator to run discovery.
            node_ip, node_name = _find_live_vm_node_ip(cfg, vmid, node)
            if node_ip:
                out, ok, method = _guest_agent_network_json(cfg, vmid, node_ip, node_name)
                if ok:
                    resolved_ip = _extract_guest_ipv4(out) or resolved_ip
                else:
                    logger.warn(
                        f"terminal: {method} guest-agent IP lookup failed for VMID {vmid}"
                        + (f" on {node_name or node_ip}" if node_name or node_ip else "")
                    )

        if resolved_ip == target:
            json_response(
                handler,
                {
                    "error": (
                        f"Cannot resolve guest IP for VMID {vmid}. "
                        "The VM is visible in PVE, but QEMU guest-agent did not return a usable IPv4 address."
                    )
                },
                400,
            )
            return

    htype = params.get("htype", ["linux"])[0]
    # Build SSH command with device-type-aware options. Physical devices use
    # the same auth family as their read APIs, not unreadable root-only staged
    # credential files.
    auth = _terminal_ssh_auth(cfg, htype)
    key_path = auth["key_path"]
    ssh_user = auth["user"] or cfg.ssh_service_account or "freq-admin"
    password_file = auth.get("password_file") or None
    sudo_password_file = auth.get("sudo_password_file", False)
    local_user = auth.get("local_user") or None

    ok, preflight_error = _terminal_preflight(cfg, htype, resolved_ip, auth)
    if not ok:
        json_response(handler, {"error": preflight_error}, 400)
        return

    if term_type == "ct":
        # SSH to PVE node, then pct exec into container
        if not node:
            from freq.modules.pve import _find_reachable_node

            node = _find_reachable_node(cfg)
            if not node:
                json_response(handler, {"error": "No PVE node reachable"}, 400)
                return
        cmd = shlex.join(
            _build_ssh_cmd(
                host=node,
                command=f"sudo pct enter {target}",
                user=ssh_user,
                key_path=key_path,
                htype=htype,
                use_sudo=False,
                extra_opts=["-tt"],
                local_user=local_user,
                password_file=password_file,
                sudo_password_file=sudo_password_file,
                cfg=cfg,
            )
        )
    else:
        cmd = shlex.join(
            _build_ssh_cmd(
                host=resolved_ip,
                command="",
                user=ssh_user,
                key_path=key_path,
                htype=htype,
                use_sudo=False,
                extra_opts=["-tt"],
                local_user=local_user,
                password_file=password_file,
                sudo_password_file=sudo_password_file,
                cfg=cfg,
            )
        )

    # Spawn in PTY. iDRAC uses subprocess+openpty instead of pty.fork()
    # because forking a threaded HTTPS request handler while opening a legacy
    # BMC SSH session can leave the POST response hung behind inherited fds.
    try:
        if htype == "idrac":
            with serve_module.IDRAC_SESSION_LOCK:
                since = time.monotonic() - serve_module._idrac_last_session_at
                if since < IDRAC_TERMINAL_SPAWN_GAP_SECONDS:
                    time.sleep(IDRAC_TERMINAL_SPAWN_GAP_SECONDS - since)
                fd, slave_fd = pty.openpty()
                try:
                    env = os.environ.copy()
                    env["TERM"] = "xterm-256color"
                    proc = subprocess.Popen(
                        ["bash", "-c", cmd],
                        stdin=slave_fd,
                        stdout=slave_fd,
                        stderr=slave_fd,
                        close_fds=True,
                        start_new_session=True,
                        env=env,
                    )
                    pid = proc.pid
                    serve_module._idrac_last_session_at = time.monotonic()
                finally:
                    os.close(slave_fd)
        else:
            pid, fd = pty.fork()
            if pid == 0:
                # Child — exec SSH
                os.environ["TERM"] = "xterm-256color"
                os.execlp("bash", "bash", "-c", cmd)
                os._exit(1)
    except OSError as e:
        logger.error(f"api_terminal_error: PTY spawn failed: {e}", endpoint="terminal/open")
        json_response(handler, {"error": f"PTY spawn failed: {e}"}, 500)
        return

    # Parent — store session
    # Set PTY size
    try:
        import fcntl
        import termios

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

    # F8 of R-SECURITY-TRUST-AUDIT-20260413P: bind the session to the
    # creator's username so the WS endpoint can refuse cross-user binds.
    # Pre-fix any logged-in operator who captured another operator's
    # session id (via URL-history / proxy-log leakage) could hijack the
    # PTY and inherit the device credentials it was opened with.
    creator = current_user(handler)
    session_id = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[session_id] = {
            "fd": fd,
            "pid": pid,
            "type": term_type,
            "htype": htype,
            "target": target,
            "created": time.time(),
            "last_active": time.time(),
            "cols": cols,
            "rows": rows,
            "user": creator,
            "kill_pgrp": htype == "idrac",
        }

    json_response(
        handler,
        {
            "ok": True,
            "session": session_id,
            "type": term_type,
            "target": target,
        },
    )


def handle_terminal_close(handler):
    """POST /api/terminal/close — close a terminal session."""
    if require_post(handler, "Terminal close"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = get_params(handler)
    session_id = params.get("session", [""])[0]
    with _sessions_lock:
        if session_id in _sessions:
            _kill_session(session_id)
    json_response(handler, {"ok": True})


def handle_terminal_resize(handler):
    """POST /api/terminal/resize — resize terminal."""
    if require_post(handler, "Terminal resize"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = get_params(handler)
    session_id = params.get("session", [""])[0]
    cols = int(params.get("cols", ["120"])[0])
    rows = int(params.get("rows", ["30"])[0])

    with _sessions_lock:
        s = _sessions.get(session_id)
        if not s:
            json_response(handler, {"error": "Session not found"}, 404)
            return
        try:
            import fcntl
            import termios

            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(s["fd"], termios.TIOCSWINSZ, winsize)
            s["cols"] = cols
            s["rows"] = rows
        except Exception as e:
            logger.warn(f"api_terminal: resize failed: {e}", endpoint="terminal/resize")
            json_response(handler, {"error": str(e)}, 400)
            return

    json_response(handler, {"ok": True})


def handle_terminal_sessions(handler):
    """GET /api/terminal/sessions — list active terminal sessions."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    _cleanup_stale()
    with _sessions_lock:
        sessions = []
        for sid, s in _sessions.items():
            sessions.append(
                {
                    "session": sid[:8] + "...",
                    "type": s["type"],
                    "target": s["target"],
                    "age": int(time.time() - s["created"]),
                    "idle": int(time.time() - s["last_active"]),
                }
            )
    json_response(handler, {"sessions": sessions, "count": len(sessions)})


# ── WebSocket Handler ──────────────────────────────────────────────────

# WebSocket magic GUID per RFC 6455
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def handle_terminal_ws(handler):
    """WebSocket endpoint — bridges xterm.js ↔ PTY.

    Hijacks the HTTP connection: sends 101 via raw socket sendall(),
    drains any data buffered by rfile, then bridges PTY ↔ WebSocket.

    F8 of R-SECURITY-TRUST-AUDIT-20260413P: the WS endpoint MUST
    refuse to bind a session that wasn't created by the same logged-
    in user. Without this check, any operator who captured another
    operator's session id (URL history, proxy logs, dev-tools
    network panel) could hijack the PTY.
    """
    from urllib.parse import urlparse, parse_qs

    role, err = _check_session_role(handler, "operator")
    if err:
        handler.send_error(403, err)
        return
    requesting_user = current_user(handler)
    if not requesting_user:
        handler.send_error(403, "Authentication required")
        return

    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    session_id = qs.get("session", [""])[0]

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            handler.send_error(404, "Session not found")
            return
        creator = session.get("user", "")
        if creator and creator != requesting_user:
            logger.warn(
                f"api_terminal: cross-user WS bind refused — session creator "
                f"{creator!r}, requester {requesting_user!r}",
                endpoint="terminal/ws",
            )
            handler.send_error(403, "Session belongs to another user")
            return
        fd = session["fd"]

    ws_key = handler.headers.get("Sec-WebSocket-Key", "")
    if not ws_key:
        handler.send_error(400, "Missing Sec-WebSocket-Key")
        return

    accept = base64.b64encode(hashlib.sha1((ws_key + _WS_GUID).encode()).digest()).decode()

    # Stop the HTTP handler loop from re-entering after we return
    handler.close_connection = True

    # Flush wfile to drain any prior keep-alive response data, then use
    # sock.sendall() for all WebSocket I/O (wfile is unbuffered and wraps
    # sock.send() which can do partial sends)
    sock = handler.request
    try:
        handler.wfile.flush()
    except Exception:
        pass

    raw_101 = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    ).encode()
    sock.sendall(raw_101)

    # Drain any bytes rfile's BufferedReader consumed past the HTTP headers
    rfile = handler.rfile
    leftover = b""
    if hasattr(rfile, "peek"):
        peeked = rfile.peek(65536)
        if peeked:
            leftover = rfile.read(len(peeked))

    try:
        _ws_bridge(sock, fd, session_id, leftover)
    except Exception as e:
        logger.debug(f"api_terminal: ws bridge ended: {e}")
    finally:
        with _sessions_lock:
            if session_id in _sessions:
                _kill_session(session_id)


def _ws_bridge(sock, fd, session_id, leftover=b""):
    """Bridge websocket ↔ PTY using select()."""
    sock.setblocking(True)
    sock.settimeout(30)
    with _sessions_lock:
        htype = ((_sessions.get(session_id) or {}).get("htype") or "").lower()
    idrac_wait_for_prompt = htype == "idrac"
    idrac_prompt_ready = not idrac_wait_for_prompt
    pending_input = bytearray()

    def _write_to_pty(payload):
        nonlocal pending_input
        if idrac_wait_for_prompt:
            payload = payload.replace(b"\n", b"\r")
            if not idrac_prompt_ready:
                pending_input.extend(payload)
                return True
        try:
            os.write(fd, payload)
            return True
        except OSError:
            return False

    while True:
        with _sessions_lock:
            s = _sessions.get(session_id)
            if not s:
                break
            s["last_active"] = time.time()

        # If rfile had leftover bytes, process them before entering select.
        # These bytes are in userspace — select() won't report them.
        if leftover:
            payload = _ws_decode_frame(leftover)
            if payload is None:
                break  # Close frame or corrupt data
            if payload:
                if not _write_to_pty(payload):
                    break
            leftover = b""
            continue

        try:
            rlist, _, _ = select.select([sock, fd], [], [], 1.0)
        except (ValueError, OSError):
            break

        if fd in rlist:
            try:
                data = os.read(fd, 4096)
                if not data:
                    break
                _ws_send(sock, data)
                if (
                    idrac_wait_for_prompt
                    and not idrac_prompt_ready
                    and (b"->" in data or b"/admin" in data.lower())
                ):
                    idrac_prompt_ready = True
                    if pending_input:
                        try:
                            time.sleep(0.25)
                            os.write(fd, bytes(pending_input))
                            pending_input.clear()
                        except OSError:
                            break
            except OSError:
                break

        if sock in rlist:
            payload = _ws_recv(sock)
            if payload is None:
                break
            if payload:
                if not _write_to_pty(payload):
                    break


def _ws_send(sock, data):
    """Send a websocket binary frame."""
    length = len(data)
    header = bytearray()
    header.append(0x82)  # FIN + binary opcode

    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", length))

    sock.sendall(bytes(header) + data)


def _ws_recv(sock):
    """Read one websocket frame from socket. Returns payload bytes or None on close."""
    try:
        head = _ws_read_exact(sock, 2)
    except (OSError, ConnectionError):
        return None

    if not head or len(head) < 2:
        return None

    return _ws_parse_frame(head, sock)


def _ws_decode_frame(data):
    """Parse a websocket frame from raw bytes (for leftover buffer). Returns payload or None."""
    if len(data) < 2:
        return b""

    return _ws_parse_frame(data[:2], None, data[2:])


def _ws_parse_frame(head, sock, remaining=b""):
    """Parse frame given 2-byte header. Reads additional bytes from sock or remaining buffer."""
    opcode = head[0] & 0x0F
    if opcode == 0x08:
        return None  # Close frame

    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F

    def _read(n):
        nonlocal remaining
        if remaining:
            chunk = remaining[:n]
            remaining = remaining[n:]
            return chunk if len(chunk) == n else None
        if sock:
            return _ws_read_exact(sock, n)
        return None

    if length == 126:
        ext = _read(2)
        if not ext:
            return None
        length = struct.unpack(">H", ext)[0]
    elif length == 127:
        ext = _read(8)
        if not ext:
            return None
        length = struct.unpack(">Q", ext)[0]

    mask_key = b""
    if masked:
        mask_key = _read(4)
        if not mask_key:
            return None

    payload = _read(length)
    if not payload:
        return None if length > 0 else b""

    if masked:
        payload = bytearray(payload)
        for i in range(len(payload)):
            payload[i] ^= mask_key[i % 4]
        payload = bytes(payload)

    # Handle ping — just acknowledge, pong is sent by bridge caller if needed
    if opcode == 0x09:
        return b""

    return payload


def _ws_read_exact(sock, n):
    """Read exactly n bytes from socket."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (BlockingIOError, TimeoutError):
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _ws_send_pong(sock, data):
    """Send a websocket pong frame."""
    header = bytearray([0x8A, len(data)])
    sock.sendall(bytes(header) + data)


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register terminal API routes."""
    routes["/api/terminal/open"] = handle_terminal_open
    routes["/api/terminal/close"] = handle_terminal_close
    routes["/api/terminal/resize"] = handle_terminal_resize
    routes["/api/terminal/sessions"] = handle_terminal_sessions
    routes["/api/terminal/ws"] = handle_terminal_ws
