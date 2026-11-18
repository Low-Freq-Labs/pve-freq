"""Original HTTP route + real helper composition, using temporary runtime state.

Only session lookup and provider fetch are substituted. HTTP transport is an
in-memory request from a configured trusted loopback proxy, not a TLS listener.
Real dispatch, role/CSRF/Origin policy, body parsing, config loading, credential
files, metadata projection and inventory projection all execute. No real user,
provider, sign-in, deployment or browser acceptance is claimed.
"""
import io
import json
from email.message import Message
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch


class EndpointCompositionTests(unittest.TestCase):
    def setUp(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        self.root = Path(runtime.name)
        for name in ('conf', 'data', 'credentials', 'data/keys', 'data/vault', 'data/log'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.conf = self.root / 'conf' / 'freq.toml'
        self.conf.write_text(
            '[paths]\ncredentials_dir = ' + json.dumps(str(self.root / 'credentials')) + '\n'
            '[services]\nwatchdog_enabled = false\ntrusted_proxy_cidrs = ["127.0.0.1/32"]\n'
            '[pve]\nnodes = []\n'
        )
        env = patch.dict('os.environ', {'FREQ_DIR': str(self.root)})
        env.start()
        self.addCleanup(env.stop)

        # Imports do not start serve/cmd_serve, a listener or a background job.
        from freq.api import auth, pve_read
        from freq.core import config, log, read_source_epoch as epoch
        from freq.modules import serve
        from freq.services import pve_read_inventory as inventory
        from freq.services.pve_transport import _pve_api_credentials
        self.auth, self.api, self.config = auth, pve_read, config
        self.epoch, self.serve, self.inventory = epoch, serve, inventory
        self.credentials = _pve_api_credentials

        # Isolate actual caches, epoch tables and log destinations, not methods.
        values = [(config, '_config_cache', None), (config, '_config_cache_ts', 0),
                  (config, '_config_cache_install_dir', None),
                  (config, '_config_cache_file_state', None),
                  (epoch, '_reads_retired', False), (epoch, '_epoch', object()),
                  (epoch, '_writers', {}), (epoch, '_readers', {}),
                  (serve.FreqHandler, '_ROUTE_REGISTRY', None),
                  (log, '_LOG_FILE', str(self.root / 'data/log/requests.jsonl')),
                  (log, '_DB_PATH', ''), (log, '_db_conn', None),
                  (log, '_stderr_enabled', False), (log, '_context', {})]
        for module, name, value in values:
            setting = patch.object(module, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.session = {'user': 'fixture-operator', 'role': 'admin', 'csrf_token': 'fixture-csrf'}
        self.lookup = Mock(side_effect=lambda token, **_kwargs:
                           self.session if token == 'fixture-session' else None)
        lookup = patch.object(auth, '_lookup_session', self.lookup)
        lookup.start()
        self.addCleanup(lookup.stop)
        self.before_cfg = config.load_config(force=True)
        self.body = {'addresses': ['pve.example'], 'token_id': 'fixture-reader@pve!Exact-Demo',
                     'token_secret': 'FICTIONAL-only-composition-secret', 'ca_pem': ''}

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for folder in ('conf', 'credentials')
                for p in (self.root / folder).rglob('*') if p.is_file()}

    def request(self, method, path, body=None, **overrides):
        handler = self.serve.FreqHandler.__new__(self.serve.FreqHandler)
        handler.command, handler.path = method, path
        handler.requestline = method + ' ' + path + ' HTTP/1.1'
        handler.request_version = 'HTTP/1.1'
        handler.client_address = ('127.0.0.1', 0)
        handler.connection = handler.request = object()
        handler.server = type('InMemoryTransport', (), {'freq_read_only': True})()
        handler.close_connection = False
        raw = json.dumps(body).encode() if body is not None else b''
        fields = {'Host': 'demo.example', 'Cookie': 'freq_session=fixture-session',
                  'X-Forwarded-Proto': 'https'}
        if body is not None:
            fields.update({'Content-Type': 'application/json', 'Content-Length': str(len(raw)),
                           'Origin': 'https://demo.example', 'X-Freq-CSRF': 'fixture-csrf'})
        fields.update(overrides)
        handler.headers = Message()
        for key, value in fields.items():
            if value is not None:
                handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler._begin_request()
        handler._dispatch_and_finish()
        wire = handler.wfile.getvalue()
        headers, payload = wire.split(b'\r\n\r\n', 1)
        status = int(headers.split(b' ', 2)[1])
        decoded = json.loads(payload)
        self.assertNotIn(self.body['token_secret'].encode(), wire)
        self.assertNotIn(self.body['token_id'].encode(), wire)
        self.assertNotIn(str(self.root / 'credentials').encode(), wire)
        self.assertIn(b'Cache-Control: no-store', headers)
        self.assertIn(b'X-Request-ID: ' + handler._request_id.encode(), headers)
        return status, decoded

    def test_original_post_blank_ca_then_retired_metadata_reload_and_inventory(self):
        status, saved = self.request('POST', '/api/pve/endpoints', self.body)
        self.assertEqual(status, 200)
        expected = {'addresses': ['pve.example'], 'token_principal': 'fixture-reader@pve',
                    'ca_configured': False}
        self.assertEqual(saved, dict(expected, ok=True))
        persisted = tomllib.loads(self.conf.read_text())['pve']
        secret_file = Path(persisted['api_token_secret_path'])
        self.assertEqual(persisted['api_token_id'], self.body['token_id'])
        self.assertEqual(secret_file.read_text(), self.body['token_secret'])
        self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(persisted['api_ca_path'], '')

        # Reproduce normal first-admin startup's permanent read retirement.
        self.epoch.retire_process_reads()
        with self.assertRaises(self.epoch.SourceReadUnavailable):
            with self.epoch.source_read():
                self.fail('original qualified read gate must remain refused')
        self.assertEqual(self.request('GET', '/api/pve/endpoints'), (200, expected))
        cfg = self.config.load_config(force=True)
        self.assertIsNot(cfg, self.before_cfg)
        self.assertEqual(cfg.credentials_dir, str(self.root / 'credentials'))
        self.assertEqual(cfg.pve_nodes, ['pve.example'])
        self.assertEqual(cfg.pve_api_token_id, self.body['token_id'])
        self.assertEqual(cfg.pve_api_token_secret, self.body['token_secret'])
        self.assertTrue(cfg.pve_api_verify_ssl)
        self.assertEqual(cfg.pve_api_ca_file, '')

        def provider(actual_cfg, source, timeout, *, deadline, now):
            self.assertIs(actual_cfg, cfg)
            self.assertEqual(source, 'pve.example')
            self.assertGreater(timeout, 0)
            self.assertGreater(deadline, now())
            self.assertEqual(self.credentials(actual_cfg, source),
                             (self.body['token_id'], self.body['token_secret']))
            return [{'type': 'node', 'node': 'fixture-node', 'status': 'online'},
                    {'type': 'qemu', 'node': 'fixture-node', 'vmid': 99001,
                     'name': 'fixture-guest', 'status': 'stopped'}]

        fetch = Mock(side_effect=provider)
        self.session['role'] = 'viewer'
        before_read = self.snapshot()
        with patch.object(self.inventory, '_fetch', fetch):
            status, report = self.request('GET', '/api/pve/inventory')
        self.assertEqual(status, 200)
        self.assertEqual(report['state'], 'ok')
        self.assertTrue(report['read_only'])
        self.assertEqual(report['sources'][0]['source'], 'pve.example')
        self.assertEqual(report['sources'][0]['nodes'][0]['node'], 'fixture-node')
        self.assertEqual(report['sources'][0]['guests'][0]['vmid'], 99001)
        fetch.assert_called_once()
        self.assertEqual(self.snapshot(), before_read)
        self.assertEqual(self.epoch._writers, {})
        self.assertEqual(self.epoch._readers, {})
        logs = (self.root / 'data/log/requests.jsonl').read_text()
        self.assertNotIn(self.body['token_secret'], logs)
        self.assertNotIn(str(secret_file), logs)

    def test_admin_csrf_origin_and_https_refuse_before_configuration_writes(self):
        baseline = self.snapshot()
        cases = [('unauthenticated', 'admin', {'Cookie': None}),
                 ('viewer', 'viewer', {}), ('operator', 'operator', {}),
                 ('missing-csrf', 'admin', {'X-Freq-CSRF': None}),
                 ('wrong-csrf', 'admin', {'X-Freq-CSRF': 'incorrect'}),
                 ('missing-origin', 'admin', {'Origin': None}),
                 ('cross-origin', 'admin', {'Origin': 'https://elsewhere.example'}),
                 ('cleartext', 'admin', {'X-Forwarded-Proto': 'http'})]
        for name, role, headers in cases:
            with self.subTest(case=name):
                self.session['role'] = role
                status, _reply = self.request('POST', '/api/pve/endpoints', self.body, **headers)
                self.assertEqual(status, 403)
                self.assertEqual(self.snapshot(), baseline)
                self.assertEqual(list((self.root / 'credentials').iterdir()), [])
        self.assertEqual(self.epoch._writers, {})

    def test_invalid_real_helper_body_has_no_configuration_effect(self):
        baseline = self.snapshot()
        for body in ({'endpoints': []}, dict(self.body, token_secret_path='/tmp/untrusted'),
                     dict(self.body, addresses=['https://pve.example']),
                     dict(self.body, ca_pem='not a certificate')):
            with self.subTest(fields=list(body)):
                status, reply = self.request('POST', '/api/pve/endpoints', body)
                self.assertEqual(status, 400)
                self.assertIn(reply['error'], {'invalid_request', 'invalid_address', 'invalid_ca'})
                self.assertEqual(self.snapshot(), baseline)

    def test_create_conflict_preserves_existing_files_and_safe_get(self):
        self.assertEqual(self.request('POST', '/api/pve/endpoints', self.body)[0], 200)
        baseline = self.snapshot()
        status, reply = self.request('POST', '/api/pve/endpoints',
                                     dict(self.body, token_secret='different-fictional-secret'))
        self.assertEqual(status, 409)
        self.assertEqual(reply['error'], 'already_configured')
        self.assertEqual(self.snapshot(), baseline)
        status, metadata = self.request('GET', '/api/pve/endpoints')
        self.assertEqual(status, 200)
        self.assertEqual(set(metadata), {'addresses', 'token_principal', 'ca_configured'})
        self.session['role'] = 'viewer'
        self.assertEqual(self.request('GET', '/api/pve/endpoints')[0], 403)
        self.assertEqual(self.snapshot(), baseline)


if __name__ == '__main__':
    unittest.main()
