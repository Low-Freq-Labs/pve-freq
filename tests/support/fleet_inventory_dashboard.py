"""Restricted synthetic-state host for the original missing Fleet inventory route.

Test source only: no native producer, installation or credential acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import ssl
import sys
import tempfile
import threading

from tests.support.hermetic_dashboard import (
    _config, _generate_tls_certificate, _install_fixture,
)
from freq.api import auth
from freq.modules import serve

INVENTORY = '/api/pve/cluster-observation/inventory'
SHELL = frozenset(('/', '/dashboard', '/dashboard/fleet', '/dashboard/home'))
GETS = frozenset(('/healthz', '/api/auth/verify', '/api/setup/status', INVENTORY))
POSTS = frozenset(('/api/auth/login', '/api/auth/logout'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be an unprivileged local port')
    evidence = Path(os.environ['PVE_FREQ_FLEET_EVIDENCE']).resolve(strict=True)
    if not evidence.is_dir():
        parser.error('evidence must be an existing directory')
    denial_path = evidence / 'python-denials.jsonl'
    rejection_path = evidence / 'server-rejections.jsonl'
    # Exclusive output avoids silently erasing evidence from an earlier run.
    denial_path.touch(exist_ok=False)
    rejection_path.touch(exist_ok=False)
    lock = threading.Lock()
    denied = []

    def record(path, value):
        with lock, path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value) + '\n')

    with tempfile.TemporaryDirectory(prefix='freq-fleet-unavailable-') as tmp:
        root = Path(tmp)
        with (evidence / 'lifecycle-start.json').open('x', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid(), 'uid': os.getuid(), 'temp_root': str(root),
                       'port': args.port}, stream)
        cfg = _config(root)
        cert, key = _generate_tls_certificate(root)
        cfg.tls_cert, cfg.tls_key = str(cert), str(key)
        _install_fixture(cfg)
        # The existing verifier is fictional; '$' avoids real legacy migration.
        synthetic_password = 'synthetic$no-real-credential'
        auth.vault_get = lambda *a, **kw: synthetic_password
        serve.vault_get = lambda *a, **kw: synthetic_password
        for marker in (Path(cfg.conf_dir, '.initialized'),
                       Path(cfg.conf_dir, '.web-setup-complete'),
                       Path(cfg.data_dir, 'setup-complete')):
            marker.write_text('synthetic fixture only\n', encoding='utf-8')
        serve._bg_cache.clear()
        serve._bg_cache_ts.clear()
        serve._bg_cache_errors.clear()

        def audit(event, _args):
            if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen',
                         'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty'} \
                    or event.startswith('os.exec') or event.startswith('os.spawn'):
                # Never log arguments, which could contain credentials.
                denied.append(event)
                record(denial_path, {'event': event, 'denied': True})
                raise PermissionError('Fleet fixture denied external effect')

        # TLS generation above is the single deliberate native child allowance.
        # This is an audit guard, not an OS sandbox or import-effect qualification.
        sys.addaudithook(audit)

        class RestrictedHandler(serve.FreqHandler):
            def _dispatch(self):
                path = self.path.split('?', 1)[0]
                allowed = (self.command == 'GET' and
                           (path in SHELL or path in GETS or path.startswith('/static/')))
                allowed = allowed or (self.command == 'POST' and path in POSTS)
                if not allowed:
                    record(rejection_path, {'method': self.command, 'path': path})
                    self.close_connection = True
                    self._json_response({'error': 'synthetic-fixture-route-denied'}, 403)
                    return
                # Original full registry and original absent-route response.
                return super()._dispatch()

        registry = RestrictedHandler._load_routes()
        if INVENTORY in registry:
            raise RuntimeError('Inventory now registered; rederive this test contract')
        httpd = serve.ThreadedHTTPServer(('127.0.0.1', args.port), RestrictedHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

        def stop(_signum, _frame):
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(f'SYNTHETIC_FLEET_UNAVAILABLE https://127.0.0.1:{args.port}', flush=True)
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
        if denied:
            raise RuntimeError('External effects were denied; inspect python-denials.jsonl')
    with (evidence / 'lifecycle-complete.json').open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'temp_root': str(root),
                   'temp_root_exists': root.exists(), 'server_closed': True,
                   'denials': len(denied)}, stream)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
