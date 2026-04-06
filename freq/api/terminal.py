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
import os
import pty
import secrets
import select
import signal
import struct
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
        stale = [sid for sid, s in _sessions.items() if now - s["last_active"] > _SESSION_TIMEOUT]
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
    target = params.get("target", [""])[0]  # IP or CTID
    node = params.get("node", [""])[0]  # PVE node IP (for ct type)
    cols = int(params.get("cols", ["120"])[0])
    rows = int(params.get("rows", ["30"])[0])

    if not target:
        json_response(handler, {"error": "target parameter required"})
        return

    # Validate target — must be IP or numeric VMID/CTID, no shell metacharacters
    import re as _re

    if not _re.match(r"^[a-zA-Z0-9._:-]+$", target):
        json_response(handler, {"error": "Invalid target (alphanumeric, dots, colons, hyphens only)"})
        return
    if node and not _re.match(r"^[a-zA-Z0-9._:-]+$", node):
        json_response(handler, {"error": "Invalid node parameter"})
        return

    # Resolve target IP for VMs (target can be IP or VMID)
    resolved_ip = target
    if term_type == "vm" and target.isdigit():
        vmid = int(target)

        # 1. Fleet registry (hosts.toml) — instant, no SSH needed
        for h in cfg.hosts:
            if getattr(h, "vmid", 0) == vmid:
                resolved_ip = h.ip
                break
        else:
            # 2. PVE guest agent — slower but authoritative
            from freq.modules.pve import _find_reachable_node, _pve_cmd

            node_ip = node or _find_reachable_node(cfg)
            if node_ip:
                out, ok = _pve_cmd(
                    cfg,
                    node_ip,
                    f"qm agent {vmid} network-get-interfaces 2>/dev/null | "
                    f"python3 -c \"import sys,json;[print(a['ip-address']) "
                    f"for i in json.load(sys.stdin) if i.get('name')!='lo' "
                    f"for a in i.get('ip-addresses',[]) if a.get('ip-address-type')=='ipv4']\" 2>/dev/null | head -1",
                    timeout=10,
                )
                if ok and out.strip():
                    resolved_ip = out.strip().split("\n")[0]

        if resolved_ip == target:
            json_response(handler, {"error": f"Cannot resolve IP for VMID {vmid}. Run 'freq discover' to populate hosts.toml with VMIDs."})
            return

    # Build SSH command with device-type-aware options
    key_path = cfg.ssh_key_path
    ssh_user = cfg.ssh_service_account or "freq-ops"
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

    # Legacy devices (iDRAC/switch) need RSA key and may need password auth
    sshpass_prefix = ""
    if htype in ("idrac", "switch"):
        rsa_key = getattr(cfg, "ssh_rsa_key_path", "")
        if rsa_key:
            ssh_opts = ssh_opts.replace(f"-i {key_path}", f"-i {rsa_key}")
        # Password auth via sshpass if configured
        pw_file = getattr(cfg, "legacy_password_file", "")
        if pw_file and os.path.isfile(pw_file):
            sshpass_prefix = f"sshpass -f {pw_file} "

    # Switch uses -T (no PTY allocation on remote — IOS doesn't support it)
    if htype == "switch":
        ssh_opts += " -T"

    if term_type == "ct":
        # SSH to PVE node, then pct exec into container
        if not node:
            from freq.modules.pve import _find_reachable_node

            node = _find_reachable_node(cfg)
            if not node:
                json_response(handler, {"error": "No PVE node reachable"})
                return
        cmd = f"ssh {ssh_opts} {ssh_user}@{node} sudo pct enter {target}"
    else:
        cmd = f"{sshpass_prefix}ssh {ssh_opts} {ssh_user}@{resolved_ip}"

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
_WS_GUID = "258EAFA5-E914-47DA-95CA-5AB5DC11DE10"


def handle_terminal_ws(handler):
    """WebSocket endpoint — bridges xterm.js ↔ PTY."""
    import traceback as _tb
    def _log(msg):
        try:
            with open("/tmp/freq-ws.log", "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    _log(f"ENTER client={handler.client_address}")
    try:
        _handle_terminal_ws_inner(handler, _log)
    except Exception as e:
        _log(f"EXCEPTION: {e}\n{''.join(_tb.format_exc())}")
        raise

def _handle_terminal_ws_inner(handler, _log):
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    session_id = qs.get("session", [""])[0]
    _log(f"session={session_id[:8]}...")

    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            _log(f"session NOT FOUND, active={len(_sessions)}")
            handler.send_error(404, "Session not found")
            return
        fd = session["fd"]
    _log(f"session found, fd={fd}")

    ws_key = handler.headers.get("Sec-WebSocket-Key", "")
    if not ws_key:
        _log("no ws key")
        handler.send_error(400, "Missing Sec-WebSocket-Key")
        return

    accept = base64.b64encode(hashlib.sha1((ws_key + _WS_GUID).encode()).digest()).decode()
    handler.close_connection = True

    # Flush wfile to drain any data buffered from prior keep-alive requests,
    # then use sock.sendall() for all WebSocket I/O. wfile (unbuffered,
    # wbufsize=0) wraps sock.send() which can do partial sends — sendall()
    # is the only safe way to guarantee complete delivery.
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
    _log(f"101 sent via sendall ({len(raw_101)}b)")

    rfile = handler.rfile
    leftover = b""
    if hasattr(rfile, "peek"):
        peeked = rfile.peek(65536)
        if peeked:
            leftover = rfile.read(len(peeked))
    _log(f"leftover={len(leftover)}b, entering bridge")

    try:
        _ws_bridge(sock, fd, session_id, leftover, _log)
    except Exception as e:
        _log(f"bridge exception: {e}")
        pass
    finally:
        with _sessions_lock:
            if session_id in _sessions:
                _kill_session(session_id)


def _ws_bridge(sock, fd, session_id, leftover=b"", _log=None):
    """Bridge websocket ↔ PTY using select()."""
    sock.setblocking(True)
    sock.settimeout(30)
    _i = 0

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
                os.write(fd, payload)
            leftover = b""
            continue

        try:
            rlist, _, _ = select.select([sock, fd], [], [], 1.0)
        except (ValueError, OSError):
            break

        _i += 1
        if fd in rlist:
            try:
                data = os.read(fd, 4096)
                if not data:
                    if _log: _log(f"i={_i} PTY EOF")
                    break
                _ws_send(sock, data)
                if _log and _i <= 3: _log(f"i={_i} sent {len(data)}b to wfile")
            except OSError as e:
                if _log: _log(f"i={_i} PTY/send err: {e}")
                break

        if sock in rlist:
            payload = _ws_recv(sock)
            if payload is None:
                if _log: _log(f"i={_i} ws closed")
                break
            if payload:
                try:
                    os.write(fd, payload)
                except OSError:
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
