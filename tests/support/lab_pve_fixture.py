"""Fictional loopback PVE lab-power provider; never contacts real infrastructure."""
import argparse
import hmac
import json
import os
from pathlib import Path
import signal
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

NODE = "synthetic-node"
VMID = 6101
NAME = "synthetic-lab-guest"
INSTANCE_UUID = "12345678-1234-5678-9123-123456789abc"
VMGENID = "22345678-1234-5678-9123-123456789abc"
TOKEN_ID = "fixture@pve!lab"
GUEST_PATH = f"/api2/json/nodes/{NODE}/qemu/{VMID}"


class FictionalLab:
    """Pure in-memory task transitions; no provider/native command execution."""
    def __init__(self):
        self.state = "running"
        self.tasks = {}
        self.counts = {"gets": 0, "config": 0, "status": 0, "task": 0, "permissions": 0,
                       "controlPosts": 0, "actions": [], "denied": 0,
                       "initialState": "running", "finalState": "running"}

    def read(self, path):
        if path == "/api2/json/access/permissions?path=%2Fvms%2F6101":
            self.counts["gets"] += 1
            self.counts["permissions"] += 1
            # Exact integer zero means the privilege is present; it is not denial.
            return {"/vms/6101": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
        if path == GUEST_PATH + "/config":
            self.counts["gets"] += 1
            self.counts["config"] += 1
            return {"node": NODE, "vmid": VMID, "name": NAME,
                    "smbios1": "uuid=" + INSTANCE_UUID, "vmgenid": VMGENID}
        if path == GUEST_PATH + "/status/current":
            self.counts["gets"] += 1
            self.counts["status"] += 1
            return {"node": NODE, "vmid": VMID, "name": NAME, "status": self.state}
        for upid, task in self.tasks.items():
            if path != f"/api2/json/nodes/{NODE}/tasks/{quote(upid, safe='')}/status":
                continue
            self.counts["gets"] += 1
            self.counts["task"] += 1
            task["reads"] += 1
            result = {"upid": upid, "node": NODE,
                      "type": "qmstart" if task["action"] == "start" else "qmshutdown",
                      "id": str(VMID), "user": "fixture@pve", "tokenid": "lab",
                      "status": "running" if task["reads"] == 1 else "stopped"}
            if task["reads"] >= 2:
                result["exitstatus"] = "OK"
                if not task["applied"]:
                    self.state = "running" if task["action"] == "start" else "stopped"
                    self.counts["finalState"] = self.state
                    task["applied"] = True
            return result
        return None

    def submit(self, path, body):
        action = "start" if path == GUEST_PATH + "/status/start" else "shutdown" if path == GUEST_PATH + "/status/shutdown" else None
        if action is None or body != (b"" if action == "start" else b"forceStop=0&timeout=30"):
            return None
        if self.state != ("stopped" if action == "start" else "running") or any(not task["applied"] for task in self.tasks.values()):
            return None
        number = self.counts["controlPosts"] + 1
        task_type = "qmstart" if action == "start" else "qmshutdown"
        upid = f"UPID:{NODE}:{number:08x}:00000001:00000002:{task_type}:{VMID}:{TOKEN_ID}:"
        self.tasks[upid] = {"action": action, "reads": 0, "applied": False}
        self.counts["controlPosts"] += 1
        self.counts["actions"].append(action)
        return upid


def main():
    parser = argparse.ArgumentParser()
    for argument in ("cert", "key", "token-file", "counts"):
        parser.add_argument("--" + argument, required=True)
    args = parser.parse_args()
    if not all(Path(value).is_absolute() for value in vars(args).values()):
        raise ValueError("invalid_fixture_paths")
    token = json.loads(Path(args.token_file).read_text(encoding="utf-8"))
    if (type(token) is not dict or set(token) != {"id", "secret"} or token["id"] != TOKEN_ID
            or type(token["secret"]) is not str or not token["secret"]
            or not all(33 <= ord(char) <= 126 for char in token["secret"])):
        raise ValueError("invalid_fixture_token")
    expected = "PVEAPIToken=" + TOKEN_ID + "=" + token["secret"]
    lab, lock = FictionalLab(), threading.Lock()
    destination = Path(args.counts)

    def persist():
        descriptor, temporary = tempfile.mkstemp(prefix=".lab-pve-counts-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(lab.counts, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, data):
            raw = json.dumps({"data": data}, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def deny(self, status=405):
            with lock:
                lab.counts["denied"] += 1
                persist()
            self.reply(status, None)

        def authorized(self):
            headers = self.headers.get_all("Authorization", [])
            return len(headers) == 1 and hmac.compare_digest(headers[0].encode("utf-8"), expected.encode("ascii"))

        def do_GET(self):
            if not self.authorized():
                return self.deny(403)
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
                return self.deny(400)
            with lock:
                data = lab.read(self.path)
                if data is not None:
                    persist()
            if data is None:
                return self.deny(404)
            self.reply(200, data)

        def do_POST(self):
            if not self.authorized():
                return self.deny(403)
            lengths = self.headers.get_all("Content-Length", [])
            if (self.headers.get("Transfer-Encoding") or len(lengths) != 1
                    or lengths[0] not in ("0", str(len(b"forceStop=0&timeout=30")))
                    or self.headers.get("Content-Type") != "application/x-www-form-urlencoded"):
                return self.deny(400)
            body = self.rfile.read(int(lengths[0]))
            with lock:
                upid = lab.submit(self.path, body)
                if upid is not None:
                    persist()
            if upid is None:
                return self.deny(405)
            self.reply(200, upid)

        def send_error(self, _code, message=None, explain=None):
            self.deny(405)

        do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_TRACE = lambda self: self.deny()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)

    class Server(ThreadingHTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            try:
                return context.wrap_socket(connection, server_side=True), address
            except Exception:
                connection.close()
                raise

        def handle_error(self, request, client_address):
            pass  # No private HTTP/provider exception strings reach stderr.

    server = Server(("127.0.0.1", 8006), Handler)
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with lock:
        persist()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        with lock:
            persist()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Synthetic lab fixture could not complete; private details withheld.") from None
