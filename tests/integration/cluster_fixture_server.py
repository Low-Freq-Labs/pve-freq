"""Explicit loopback-only server for the offline Cluster Status package journey.

Run only in the approved test environment. This is not a production startup
path, authentication/login qualification, or provider connection. It uses real
registered Fleet/bind/read handlers and serves the packaged frontend assets.
"""
import argparse
import json
import signal
import ssl
import threading
import time
from pathlib import Path

from freq.api import auth, fleet
from freq.modules import serve
from freq.services.cluster_service import SuppliedClusterService


# Deliberately public synthetic values, valid only in this loopback fixture.
FIXTURE_SESSION = 'offline-cluster-fixture-session'
FIXTURE_CSRF = 'offline-cluster-fixture-csrf'


def create_server(port=0, *, shape='positive', read_delay=0.0):
    if shape not in ('positive', 'empty', 'unavailable') or not 0 <= read_delay <= 9:
        raise ValueError('invalid fixture selection')
    rows = [] if shape == 'empty' else [
        {'id': 'node/fixture-node', 'name': 'fixture-node', 'type': 'node',
         'online': 1, 'local': 1, 'nodeid': 1, 'ip': '192.0.2.10'},
    ]
    raw = json.dumps(rows, separators=(',', ':')).encode('utf-8')
    def supplied_reader(target, deadline):
        if read_delay:
            time.sleep(read_delay)
        if shape == 'unavailable':
            raise ValueError('fixture unavailable')
        return raw
    service = SuppliedClusterService({'fixture-node': '192.0.2.10'}, supplied_reader)

    class FixtureHandler(serve.FreqHandler):
        def _dispatch(self):
            path = self.path.split('?', 1)[0]
            allowed = {'/', '/dashboard', '/api/fleet/overview',
                       '/api/auth/verify', '/api/auth/logout',
                       '/api/pve/cluster-report/bind', '/api/pve/cluster-report/read'}
            if path not in allowed and not path.startswith('/static/'):
                self.close_connection = True
                self._json_response({'error': 'offline_fixture_route_unavailable'}, 503)
                return
            super()._dispatch()

    class FixtureServer(serve.ThreadedHTTPServer):
        # Unlike the product default, fixture closure joins request threads.
        daemon_threads = False
        block_on_close = True
        tls_context = None

        def get_request(self):
            connection, address = self.socket.accept()
            try:
                connection.settimeout(10.0)
                if self.tls_context is None:
                    raise RuntimeError('fixture TLS context not installed')
                return self.tls_context.wrap_socket(connection, server_side=True), address
            except BaseException:
                connection.close()
                raise

    server = FixtureServer(('127.0.0.1', port), FixtureHandler)
    try:
        server.cluster_report_service = service
        now = time.time()
        with auth._auth_lock:
            auth._auth_tokens[FIXTURE_SESSION] = dict(
                user='offline-fixture', role='viewer', ts=now,
                last_activity_ts=now, csrf_token=FIXTURE_CSRF)
        # Bootstrapping is explicit; no production config or credential loader runs.
        serve._is_first_run = lambda: False
        fleet._bg_cache = {'fleet_overview': {
            'pve_nodes': [{'name': 'fixture-node', 'ip': '192.0.2.10', 'online': True,
                           'state': 'unknown', 'type': 'pve', 'vmid': 0,
                           'detail': 'Offline supplied Cluster Status fixture'}],
            'vms': [], 'physical': [], 'vm_nics': {}, 'vlans': [], 'nic_profiles': {},
            'categories': {}, 'summary': {'resource_count': 1, 'real_vm_count': 0},
            'fleet_state': 'unknown', 'fleet_reason': 'Offline supplied fixture',
        }}
        fleet._bg_cache_ts = {'fleet_overview': now}
        fleet._bg_cache_errors = {}
        return server
    except BaseException:
        try:
            server.server_close()
        finally:
            with auth._auth_lock:
                retired = auth._auth_tokens.pop(FIXTURE_SESSION, None)
                if retired is not None:
                    service.references.retire_session(retired)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--shape', choices=('positive', 'empty', 'unavailable'), default='positive')
    parser.add_argument('--read-delay', type=float, default=0.0)
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('invalid loopback port')
    server = create_server(args.port, shape=args.shape, read_delay=args.read_delay)
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.certificate, args.private_key)
        server.tls_context = context
        def stop(signum, frame):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(json.dumps({'scope': 'offline_cluster_package',
                          'url': 'https://127.0.0.1:' + str(server.server_port),
                          'shape': args.shape}), flush=True)
        server.serve_forever(poll_interval=0.1)
    finally:
        try:
            server.server_close()
        finally:
            with auth._auth_lock:
                retired = auth._auth_tokens.pop(FIXTURE_SESSION, None)
                if retired is not None:
                    server.cluster_report_service.references.retire_session(retired)


if __name__ == '__main__':
    main()
