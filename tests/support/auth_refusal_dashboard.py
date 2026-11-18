"""Auth-refusal-only original HTTP fixture with fictional credentials/state."""
import argparse
import json
import os
from pathlib import Path
import signal
import ssl
import sys
import tempfile
import threading

from tests.support.hermetic_dashboard import _config, _generate_tls_certificate, _install_fixture
from freq.api import auth
from freq.modules import serve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('explicit unprivileged local port required')
    evidence = Path(os.environ['PVE_FREQ_AUTH_EVIDENCE']).resolve(strict=True)
    if not evidence.is_dir():
        parser.error('existing evidence directory required')
    outputs = {name: evidence / (name + '.jsonl') for name in
               ('python-denials', 'server-rejections', 'guard-violations')}
    for path in outputs.values():
        path.touch(exist_ok=False)
    lock = threading.Lock()
    denials = []
    violations = []

    def record(name, entry):
        with lock, outputs[name].open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')

    with tempfile.TemporaryDirectory(prefix='freq-auth-refusal-') as tmp:
        root = Path(tmp)
        with (evidence / 'lifecycle-start.json').open('x', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid(), 'uid': os.getuid(), 'temp_root': str(root),
                       'port': args.port}, stream)
        cfg = _config(root)
        cert, key = _generate_tls_certificate(root)
        cfg.tls_cert, cfg.tls_key = str(cert), str(key)
        _install_fixture(cfg)  # Fictional admin/operator registry; original auth handlers.
        def fictional_vault(_cfg, _namespace, key):
            return '' if key == 'password_operator' else 'synthetic$marker'
        auth.vault_get = fictional_vault
        serve.vault_get = fictional_vault
        auth.verify_password = lambda *_args, **_kwargs: False
        for marker in (Path(cfg.conf_dir, '.initialized'),
                       Path(cfg.conf_dir, '.web-setup-complete'),
                       Path(cfg.data_dir, 'setup-complete')):
            marker.write_text('synthetic fixture only\n', encoding='utf-8')
        serve._bg_cache.clear()
        serve._bg_cache_ts.clear()
        serve._bg_cache_errors.clear()

        def forbidden(name):
            def fail(*_args, **_kwargs):
                violations.append(name)
                record('guard-violations', {'operation': name, 'count': violations.count(name)})
                raise RuntimeError('Auth refusal fixture forbids mutation/session issuance')
            return fail
        for name in ('vault_init', 'vault_set', 'hash_password', 'establish_session'):
            setattr(auth, name, forbidden(name))

        def audit(event, _args):
            if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen',
                         'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty'} \
                    or event.startswith('os.exec') or event.startswith('os.spawn'):
                denials.append(event)
                record('python-denials', {'event': event, 'denied': True})
                raise PermissionError('Auth fixture denied external effect')
        # Only deliberate native child: temporary TLS generation above.
        # Imported helper effects precede this guard; this is not an OS sandbox.
        sys.addaudithook(audit)

        class AuthOnlyHandler(serve.FreqHandler):
            def _dispatch(self):
                path = self.path.split('?', 1)[0]
                allowed = self.command == 'GET' and (
                    path in ('/', '/dashboard', '/api/auth/verify', '/healthz')
                    or path.startswith('/static/'))
                allowed = allowed or self.command == 'POST' and path == '/api/auth/login'
                if not allowed:
                    record('server-rejections', {'method': self.command, 'path': path})
                    self.close_connection = True
                    self._json_response({'error': 'synthetic-auth-fixture-route-denied'}, 403)
                    return
                return super()._dispatch()

        AuthOnlyHandler._load_routes()  # Keep original complete registry.
        httpd = serve.ThreadedHTTPServer(('127.0.0.1', args.port), AuthOnlyHandler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
        def stop(_signum, _frame):
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(f'SYNTHETIC_AUTH_REFUSAL https://127.0.0.1:{args.port}', flush=True)
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
    with (evidence / 'lifecycle-complete.json').open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'temp_root': str(root),
                   'temp_root_exists': root.exists(), 'server_closed': True,
                   'denials': len(denials), 'guard_violations': len(violations)}, stream)
    if denials or violations:
        raise RuntimeError('Fixture guard failed; inspect nonsecret event logs')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
