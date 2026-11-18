"""Synthetic loopback TLS provider for original-server integration, never live PVE."""
import argparse
import hmac
import json
import os
import signal
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    for name in ('cert', 'key', 'token-file', 'counts'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    token = json.loads(Path(args.token_file).read_text())
    expected = 'PVEAPIToken=' + token['id'] + '=' + token['secret']
    counts = {'inventory': 0, 'denied': 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
                with lock:
                    counts['denied'] += 1
                return self.respond(403, {'error': 'denied'})
            if self.path == '/api2/json/cluster/resources':
                with lock:
                    counts['inventory'] += 1
                    observation = counts['inventory']
                rows = [{'type': 'node', 'node': 'synthetic-node', 'name': 'synthetic-node', 'status': 'online', 'cpu': 0.05,
                         'mem': 1073741824, 'maxmem': 8589934592, 'uptime': 120,
                         'disk': 1073741824, 'maxdisk': 68719476736},
                        {'type': 'qemu', 'node': 'synthetic-node', 'vmid': 6101,
                         'name': 'synthetic-guest', 'status': 'running', 'template': 0,
                         'cpu': 0.02, 'mem': 268435456, 'maxmem': 1073741824,
                         'maxcpu': 2, 'uptime': 60 + observation, 'disk': 0, 'maxdisk': 8589934592}]
            else:
                return self.refuse()
            self.respond(200, {'data': rows})

        def refuse(self):
            with lock:
                counts['denied'] += 1
            self.respond(405, {'error': 'unsupported'})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = refuse

    server = ThreadingHTTPServer(('127.0.0.1', 8006), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        fd = os.open(args.counts, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(counts, stream)


if __name__ == '__main__':
    main()
