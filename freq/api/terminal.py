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
    - vm:   SSH directly to VM IP (freq-ops@<ip>)
    - ct:   SSH to PVE node, then pct exec <ctid> -- bash
    - node: SSH directly to PVE node (freq-ops@<ip>)
"""

import base64
import hashlib
import json
import os
import pty
import secrets
import select
import signal
import struct
import subprocess
import threading
import time

from freq.api.helpers import json_response, get_params
from freq.core.config import load_config
from freq.modules.serve import _check_session_role


# ── Session Store ──────────────────────────────────────────────────────

_sessions = {}
_sessions_lock = threading.Lock()
_SESSION_TIMEOUT = 900  # 15 minutes idle timeout
_MAX_SESSIONS = 20


def _cleanup_stale():
    """Remove sessions idle > timeout."""
    now = time.time()
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items()
                 if now - s["last_active"] > _SESSION_TIMEOUT]
        for sid in stale:
            _kill_session(sid)


def _kill_session(sid):
    """Kill a session's SSH process and close PTY. Must hold _sessions_lock."""
    s = _sessions.pop(sid, None)
    if not s:
        return
    try:
        os.kill(s["pid"], signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        os.close(s["fd"])
    except OSError:
        pass


# ── Session Creation ───────────────────────────────────────────────────


def handle_terminal_open(handler):
    """POST /api/terminal/open — create a new terminal session."""
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
    term_type = params.get("type", ["vm"])[0]  # vm, ct, node
    target = params.get("target", [""])[0]      # IP or CTID
    node = params.get("node", [""])[0]           # PVE node IP (for ct type)
    cols = int(params.get("cols", ["120"])[0])
    rows = int(params.get("rows", ["30"])[0])

    if not target:
        json_response(handler, {"error": "target parameter required"})
        return

    # Resolve target IP for VMs (target can be IP or VMID)
    resolved_ip = target
    if term_type == "vm" and target.isdigit():
        # Target is a VMID — resolve IP via PVE guest agent or fleet data
        vmid = int(target)
        from freq.modules.pve import _find_reachable_node, _pve_cmd
        node_ip = node or _find_reachable_node(cfg)
        if node_ip:
            # Try guest agent first
            out, ok = _pve_cmd(cfg, node_ip,
                f"qm agent {vmid} network-get-interfaces 2>/dev/null | "
                f"python3 -c \"import sys,json;[print(a['ip-address']) "
                f"for i in json.load(sys.stdin) if i.get('name')!='lo' "
                f"for a in i.get('ip-addresses',[]) if a.get('ip-address-type')=='ipv4']\" 2>/dev/null | head -1",
                timeout=10)
            if ok and out.strip():
                resolved_ip = out.strip().split("\n")[0]
            else:
                # Fallback: check fleet hosts for matching VMID
                for h in cfg.hosts:
                    if getattr(h, "vmid", 0) == vmid:
                        resolved_ip = h.ip
                        break
                else:
                    # Last resort: try hosts whose label contains the vmid
                    json_response(handler, {"error": f"Cannot resolve IP for VMID {vmid}. Try using the IP directly."})
                    return

    # Build SSH command with device-type-aware options
    key_path = cfg.ssh_key_path
    ssh_user = cfg.service_account or "freq-ops"
    htype = params.get("htype", ["linux"])[0]

    # Base SSH options
    ssh_opts = (
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-o ServerAliveInterval=15 -o ServerAliveCountMax=3 "
        f"-i {key_path}"
    )

    # Device-specific SSH options from ssh.py platform config
    from freq.core.ssh import _PLATFORM_SSH_BASE
    platform = _PLATFORM_SSH_BASE.get(htype, _PLATFORM_SSH_BASE.get("linux", {}))
    extra_opts = platform.get("extra_opts", [])
    if extra_opts:
        ssh_opts += " " + " ".join(extra_opts)

    # Switch uses -T (no PTY allocation on remote — IOS doesn't support it)
    if htype == "switch":
        ssh_opts += " -T"
        # Switch may need RSA key instead of ed25519
        rsa_key = getattr(cfg, "ssh_rsa_key_path", "")
        if rsa_key:
            ssh_opts = ssh_opts.replace(f"-i {key_path}", f"-i {rsa_key}")

    # iDRAC: use RSA key if available
    if htype == "idrac":
        rsa_key = getattr(cfg, "ssh_rsa_key_path", "")
        if rsa_key:
            ssh_opts = ssh_opts.replace(f"-i {key_path}", f"-i {rsa_key}")

    if term_type == "ct":
        # SSH to PVE node, then pct exec into container
        if not node:
            from freq.modules.pve import _find_reachable_node
            node = _find_reachable_node(cfg)
            if not node:
                json_response(handler, {"error": "No PVE node reachable"})
                return
        cmd = f"ssh {ssh_opts} {ssh_user}@{node} sudo pct enter {target}"
    elif term_type == "node":
        cmd = f"ssh {ssh_opts} {ssh_user}@{resolved_ip}"
    elif htype == "pfsense":
        # pfSense — no sudo prefix, direct shell
        cmd = f"ssh {ssh_opts} {ssh_user}@{resolved_ip}"
    elif htype == "idrac":
        # iDRAC — racadm shell
        cmd = f"ssh {ssh_opts} {ssh_user}@{resolved_ip}"
    elif htype == "switch":
        # Switch — IOS CLI, no PTY
        cmd = f"ssh {ssh_opts} {ssh_user}@{resolved_ip}"
    else:
        # VM or generic host — direct SSH
        cmd = f"ssh {ssh_opts} {ssh_user}@{resolved_ip}"

    # Spawn in PTY
    try:
        pid, fd = pty.fork()
    except OSError as e:
        json_response(handler, {"error": f"PTY fork failed: {e}"}, 500)
        return

    if pid == 0:
        # Child — exec SSH
        os.environ["TERM"] = "xterm-256color"
        os.execlp("bash", "bash", "-c", cmd)
        os._exit(1)

    # Parent — store session
    # Set PTY size
    try:
        import fcntl
        import termios
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

    session_id = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[session_id] = {
            "fd": fd,
            "pid": pid,
            "type": term_type,
            "target": target,
            "created": time.time(),
            "last_active": time.time(),
            "cols": cols,
            "rows": rows,
        }

    json_response(handler, {
        "ok": True,
        "session": session_id,
        "type": term_type,
        "target": target,
    })


def handle_terminal_close(handler):
    """POST /api/terminal/close — close a terminal session."""
    params = get_params(handler)
    session_id = params.get("session", [""])[0]
    with _sessions_lock:
        if session_id in _sessions:
            _kill_session(session_id)
    json_response(handler, {"ok": True})


def handle_terminal_resize(handler):
    """POST /api/terminal/resize — resize terminal."""
    params = get_params(handler)
    session_id = params.get("session", [""])[0]
    cols = int(params.get("cols", ["120"])[0])
    rows = int(params.get("rows", ["30"])[0])

    with _sessions_lock:
        s = _sessions.get(session_id)
        if not s:
            json_response(handler, {"error": "Session not found"})
            return
        try:
            import fcntl
            import termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(s["fd"], termios.TIOCSWINSZ, winsize)
            s["cols"] = cols
            s["rows"] = rows
        except Exception as e:
            json_response(handler, {"error": str(e)})
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
            sessions.append({
                "session": sid[:8] + "...",
                "type": s["type"],
                "target": s["target"],
                "age": int(time.time() - s["created"]),
                "idle": int(time.time() - s["last_active"]),
            })
    json_response(handler, {"sessions": sessions, "count": len(sessions)})


# ── WebSocket Handler ──────────────────────────────────────────────────

# WebSocket magic GUID per RFC 6455
_WS_GUID = "258EAFA5-E914-47DA-95CA-5AB5DC11DE10"


def handle_terminal_ws(handler):
    """WebSocket endpoint — bridges xterm.js ↔ PTY.

    This hijacks the HTTP connection, performs the WebSocket handshake,
    then enters a select() loop bridging PTY fd and websocket frames.
    """
    # Extract session ID from query string
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    session_id = qs.get("session", [""])[0]

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            handler.send_error(404, "Session not found")
            return
        fd = session["fd"]

    # WebSocket handshake
    ws_key = handler.headers.get("Sec-WebSocket-Key", "")
    if not ws_key:
        handler.send_error(400, "Missing Sec-WebSocket-Key")
        return

    accept = base64.b64encode(
        hashlib.sha1((ws_key + _WS_GUID).encode()).digest()
    ).decode()

    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()

    sock = handler.request  # raw socket

    try:
        _ws_bridge(sock, fd, session_id)
    except Exception:
        pass
    finally:
        with _sessions_lock:
            if session_id in _sessions:
                _kill_session(session_id)


def _ws_bridge(sock, fd, session_id):
    """Bridge websocket ↔ PTY using select()."""
    sock.setblocking(False)

    while True:
        with _sessions_lock:
            s = _sessions.get(session_id)
            if not s:
                break
            s["last_active"] = time.time()

        try:
            rlist, _, _ = select.select([sock, fd], [], [], 1.0)
        except (ValueError, OSError):
            break

        if fd in rlist:
            # PTY has data → send to websocket as binary frame
            try:
                data = os.read(fd, 4096)
                if not data:
                    break
                _ws_send(sock, data)
            except OSError:
                break

        if sock in rlist:
            # Websocket has data → read frame, write to PTY
            try:
                payload = _ws_recv(sock)
                if payload is None:
                    break  # Connection closed
                if payload:
                    os.write(fd, payload)
            except (OSError, ConnectionError):
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
    """Read one websocket frame. Returns payload bytes or None on close."""
    try:
        head = _ws_read_exact(sock, 2)
    except (OSError, ConnectionError):
        return None

    if not head or len(head) < 2:
        return None

    opcode = head[0] & 0x0F
    if opcode == 0x08:
        return None  # Close frame

    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F

    if length == 126:
        ext = _ws_read_exact(sock, 2)
        if not ext:
            return None
        length = struct.unpack(">H", ext)[0]
    elif length == 127:
        ext = _ws_read_exact(sock, 8)
        if not ext:
            return None
        length = struct.unpack(">Q", ext)[0]

    mask_key = b""
    if masked:
        mask_key = _ws_read_exact(sock, 4)
        if not mask_key:
            return None

    payload = _ws_read_exact(sock, length)
    if not payload:
        return None

    if masked:
        payload = bytearray(payload)
        for i in range(len(payload)):
            payload[i] ^= mask_key[i % 4]
        payload = bytes(payload)

    # Handle ping
    if opcode == 0x09:
        _ws_send_pong(sock, payload)
        return b""

    return payload


def _ws_read_exact(sock, n):
    """Read exactly n bytes from socket."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except BlockingIOError:
            # Non-blocking socket, retry with select
            select.select([sock], [], [], 5.0)
            continue
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
