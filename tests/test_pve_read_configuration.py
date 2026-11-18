"""Temporary-directory configuration tests; no providers or live credentials."""
import contextlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.core.read_source_epoch import source_read, source_write
from freq.services import pve_read_configuration as service


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ca_root = tempfile.TemporaryDirectory()
        root = Path(cls.ca_root.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-subj", "/CN=local-config-test",
                        "-keyout", str(root / "key"), "-out", str(root / "ca")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.ca_pem = (root / "ca").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.ca_root.cleanup()

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        root = Path(self.root.name)
        self.conf = root / "conf"
        self.cred = root / "credentials"
        self.conf.mkdir()
        self.cred.mkdir()
        self.config = self.conf / "freq.toml"
        self.original = (b'# keep original comments\n[ssh]\nservice_account = "freq-admin"\n'
                         b'[unrelated]\nnodes = ["leave-this"]\n'
                         b'[pve]\n# operator note\nnodes = [\n # empty list\n]\n'
                         b'api_token_id = ""\n[pve.storage.node]\npool = "keep"\n')
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        self.cfg = SimpleNamespace(conf_dir=str(self.conf), credentials_dir=str(self.cred),
                                   pve_nodes=[], pve_api_token_id="", pve_api_token_secret="")
        self.body = {"addresses": ["PVE.Example.", "192.0.2.10", "2001:db8::1"],
                     "token_id": "Observer@pve!Exact-Token", "token_secret": "fictional-test-secret"}

    def configure(self, **updates):
        return service.configure_pve_read(self.cfg, dict(self.body, **updates))

    def assert_unchanged(self):
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(list(self.cred.iterdir()), [])
        self.assertEqual(list(self.conf.iterdir()), [self.config])

    def assert_error(self, code, body=None):
        with self.assertRaises(service.ConfigurationError) as caught:
            service.configure_pve_read(self.cfg, self.body if body is None else body)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(self.body["token_secret"], str(caught.exception))

    def test_exact_token_atomic_metadata_modes_and_unrelated_config(self):
        result = self.configure()
        self.assertEqual(result, {"addresses": ["pve.example", "192.0.2.10", "2001:db8::1"],
                                  "token_principal": "Observer@pve", "ca_configured": False})
        data = tomllib.loads(self.config.read_text())
        self.assertEqual(data['pve']['api_token_id'], self.body['token_id'])
        self.assertTrue(data['pve']['api_verify_ssl'])
        self.assertEqual(data['pve']['node_names'], [])
        self.assertEqual(data['unrelated'], {'nodes': ['leave-this']})
        self.assertEqual(data['pve']['storage'], {'node': {'pool': 'keep'}})
        self.assertIn('# operator note', self.config.read_text())
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        secret = Path(data['pve']['api_token_secret_path'])
        self.assertEqual(secret.read_text(), self.body['token_secret'])
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        self.assertNotIn(self.body['token_secret'], self.config.read_text())
        self.assertEqual(self.cfg.pve_nodes, [])  # Loader integration owns reload.
        self.assertEqual(service.get_pve_read_configuration(self.cfg), result)

    def test_ca_validated_and_private_file(self):
        result = self.configure(ca_pem=self.ca_pem)
        data = tomllib.loads(self.config.read_text())['pve']
        ca = Path(data['api_ca_path'])
        self.assertEqual(ca.read_text(), self.ca_pem)
        self.assertEqual(stat.S_IMODE(ca.stat().st_mode), 0o600)
        self.assertTrue(result['ca_configured'])
        self.assertNotIn('api_ca_path', result)

    def test_missing_config_created_with_private_mode(self):
        self.config.unlink()
        self.configure()
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_existing_config_refuses_second_create(self):
        self.configure()
        before = self.config.read_bytes()
        files = {p.name: p.read_bytes() for p in self.cred.iterdir()}
        self.assert_error('already_configured')
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual({p.name: p.read_bytes() for p in self.cred.iterdir()}, files)

    def test_cached_configuration_also_refused(self):
        self.cfg.pve_nodes = ['existing.example']
        self.assert_error('already_configured')
        self.assert_unchanged()

    def test_legacy_node_override_refused_without_reading_secret(self):
        import hashlib
        name = 'pve-token-rw-' + hashlib.sha256(b'pve.example').hexdigest()[:12]
        (self.cred / name).symlink_to('/does-not-exist')
        self.assert_error('already_configured')
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(len(list(self.cred.iterdir())), 1)

    def test_addresses_grammar_duplicates_count_and_types(self):
        for values in ([], ['pve'] * 9, ['PVE.example.', 'pve.example'], ['https://pve'],
                       ['pve:8006'], ['[2001:db8::1]'], ['bad host'], ['-bad'],
                       ['192.0.2.999'], ['fe80::1%eth0'], ['☃.example'], [123], 'pve'):
            with self.subTest(values=values):
                self.assert_error('invalid_address', dict(self.body, addresses=values))
                self.assert_unchanged()

    def test_eight_endpoints_allowed(self):
        self.assertEqual(len(self.configure(addresses=[f'pve{i}.example' for i in range(8)])['addresses']), 8)

    def test_token_and_secret_reject_header_delimiters_controls_and_whitespace(self):
        for key, values in {'token_id': ['missing', 'user@pve!a b', 'u@p!x\r\nX:y', '☃@p!x'],
                            'token_secret': ['', 'white space', 'x\n', 'x\t', 'x\x00', 'é', 'x'*4097]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assert_error('invalid_token', dict(self.body, **{key: value}))
                    self.assert_unchanged()

    def test_unknown_and_missing_fields(self):
        for value in (dict(self.body, token_secret_path='/tmp/secret'), {}, [],
                      dict(self.body, update=True)):
            self.assert_error('invalid_request', value)
            self.assert_unchanged()

    def test_ca_invalid_oversized_keys_and_noncertificate_text(self):
        for ca in ('/tmp/ca.pem', 'x'*65537, self.ca_pem+'PRIVATE KEY',
                   self.ca_pem+'unexpected', '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----'):
            self.assert_error('invalid_ca', dict(self.body, ca_pem=ca))
            self.assert_unchanged()

    def test_reader_gate_prevents_any_write(self):
        transaction = source_read()
        with transaction:
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_secret_write_error_sanitized_and_rolled_back(self):
        real_create = service._create
        def fail(fd, name, data, created, *args):
            real_create(fd, name, data, created, *args)
            if name.startswith('pve-read-token-'):
                raise OSError(self.body['token_secret'])
        with patch.object(service, '_create', side_effect=fail):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_config_replace_failure_restores_and_cleans(self):
        with patch.object(service.os, 'replace', side_effect=OSError('private path')):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_replace_effect_then_error_restores_original_bytes_and_mode(self):
        real_replace = service.os.replace
        calls = []
        def replace(*args, **kwargs):
            calls.append(args)
            real_replace(*args, **kwargs)
            if len(calls) == 1:
                raise OSError('uncertain replace')
        with patch.object(service.os, 'replace', side_effect=replace):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_directory_sync_failure_after_commit_rolls_back(self):
        real_sync = service.os.fsync
        conf_inode = self.conf.stat().st_ino
        failed = []
        def sync(fd):
            if os.fstat(fd).st_ino == conf_inode and not failed:
                failed.append(True)
                raise OSError('sync failure')
            return real_sync(fd)
        with patch.object(service.os, 'fsync', side_effect=sync):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_unconfirmed_rollback_retains_referenced_credentials(self):
        real_replace = service.os.replace
        calls = []
        def replace(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                real_replace(*args, **kwargs)
                raise OSError('after effect')
            raise OSError('rollback unavailable')
        with patch.object(service.os, 'replace', side_effect=replace):
            self.assert_error('configuration_unavailable')
        data = tomllib.loads(self.config.read_text())['pve']
        self.assertEqual(Path(data['api_token_secret_path']).read_text(), self.body['token_secret'])
        self.assertEqual(stat.S_IMODE(Path(data['api_token_secret_path']).stat().st_mode), 0o600)

    def test_gate_exit_failure_rolls_back_under_fresh_writer(self):
        entered = []
        @contextlib.contextmanager
        def gate():
            with source_write():
                entered.append(True)
                yield
            if len(entered) == 1:
                raise OSError('exit uncertainty')
        with patch.object(service, 'source_write', side_effect=gate):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()
        self.assertEqual(len(entered), 2)

    def test_gate_exit_and_rollback_admission_failure_retains_refs(self):
        entered = []
        @contextlib.contextmanager
        def gate():
            if entered:
                raise OSError('second gate refused')
            with source_write():
                entered.append(True)
                yield
            raise OSError('exit uncertainty')
        with patch.object(service, 'source_write', side_effect=gate):
            self.assert_error('configuration_unavailable')
        data = tomllib.loads(self.config.read_text())['pve']
        self.assertTrue(Path(data['api_token_secret_path']).exists())

    def test_symlink_config_and_directory_refused(self):
        target = self.conf / 'preserve'
        self.config.rename(target)
        self.config.symlink_to(target.name)
        self.assert_error('configuration_unavailable')
        self.assertEqual(target.read_bytes(), self.original)
        self.assertEqual(list(self.cred.iterdir()), [])
        self.config.unlink()
        target.rename(self.config)
        alias = self.conf.parent / 'alias'
        alias.symlink_to(self.cred)
        self.cfg.credentials_dir = str(alias)
        self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_get_never_reads_secret_or_ca_files(self):
        self.configure(ca_pem=self.ca_pem)
        data = tomllib.loads(self.config.read_text())['pve']
        Path(data['api_token_secret_path']).unlink()
        Path(data['api_ca_path']).unlink()
        result = service.get_pve_read_configuration(self.cfg)
        self.assertEqual(set(result), {'addresses', 'token_principal', 'ca_configured'})
        self.assertTrue(result['ca_configured'])

    def test_multiline_unrelated_table_text_and_quoted_pve_table_preserved(self):
        self.original = b"""[note]
text = \"\"\"
[pve]
nodes = [\"not-a-table\"]
\"\"\"
[\"pve\"]
nodes = []
"""
        self.config.write_bytes(self.original)
        self.configure()
        data = tomllib.loads(self.config.read_text())
        self.assertIn('[pve]', data['note']['text'])
        self.assertEqual(data['pve']['nodes'], ['pve.example', '192.0.2.10', '2001:db8::1'])

    def test_existing_legacy_shared_secret_refused(self):
        (self.cred / 'pve-token-rw').write_text('old-private-credential')
        self.assert_error('already_configured')
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual((self.cred / 'pve-token-rw').read_text(), 'old-private-credential')

    def test_ca_write_failure_cleans_previously_written_secret(self):
        real_create = service._create
        def fail(fd, name, data, created, *args):
            real_create(fd, name, data, created, *args)
            if name.startswith('pve-read-ca-'):
                raise OSError('CA write failed')
        with patch.object(service, '_create', side_effect=fail):
            self.assert_error('configuration_unavailable', dict(self.body, ca_pem=self.ca_pem))
        self.assert_unchanged()

    def test_configuration_has_no_network_or_process_calls(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')):
            result = self.configure(ca_pem=self.ca_pem)
        self.assertEqual(result['token_principal'], 'Observer@pve')

    def test_corrupt_config_returns_sanitized_error_without_credential_files(self):
        self.config.write_text('invalid = [')
        self.assert_error('configuration_unavailable')
        self.assertEqual(self.config.read_text(), 'invalid = [')
        self.assertEqual(list(self.cred.iterdir()), [])
        with self.assertRaises(service.ConfigurationError) as caught:
            service.get_pve_read_configuration(self.cfg)
        self.assertEqual(str(caught.exception), 'configuration_unavailable')

    def test_missing_credentials_directory_is_not_provisioned(self):
        self.cred.rmdir()
        self.assert_error('configuration_unavailable')
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.cred.exists())

    def test_get_empty_configuration_is_metadata_only(self):
        self.assertEqual(service.get_pve_read_configuration(self.cfg),
                         {'addresses': [], 'token_principal': '', 'ca_configured': False})

    def test_rendered_config_size_is_checked_before_new_files(self):
        with patch.object(service, '_MAX_CONFIG', len(self.original) + 10):
            self.assert_error('configuration_unavailable')
        self.assert_unchanged()

    def test_exact_ui_body_with_empty_optional_ca_succeeds(self):
        body = {"addresses": ["pve.example"], "token_id": "reader@pve!demo",
                "token_secret": "fictional-ui-token", "ca_pem": ""}
        result = service.configure_pve_read(self.cfg, body)
        self.assertEqual(result, {"addresses": ["pve.example"],
                                  "token_principal": "reader@pve", "ca_configured": False})
        data = tomllib.loads(self.config.read_text())['pve']
        self.assertEqual(data['api_ca_path'], '')
        self.assertEqual(len(list(self.cred.iterdir())), 1)

    def test_absent_null_and_whitespace_ca_normalize_to_no_ca(self):
        for body in (dict(self.body), dict(self.body, ca_pem=None),
                     dict(self.body, ca_pem=' \n\t')):
            self.assertIsNone(service._validate(body)[3])
        self.assert_error('invalid_ca', dict(self.body, ca_pem=' ' * 65537))
        self.assert_unchanged()

    def test_memory_error_preserved_by_configure_and_get_wrappers(self):
        original = MemoryError('fictional allocation failure')
        with patch.object(service, '_configure', side_effect=original):
            with self.assertRaises(MemoryError) as caught:
                service.configure_pve_read(self.cfg, self.body)
        self.assertIs(caught.exception, original)
        with patch.object(service, '_directory', side_effect=original):
            with self.assertRaises(MemoryError) as caught:
                service.get_pve_read_configuration(self.cfg)
        self.assertIs(caught.exception, original)
        self.assert_unchanged()
        self.assertEqual(service.get_pve_read_configuration(self.cfg)['addresses'], [])

    def test_passive_get_works_after_first_admin_read_retirement(self):
        from freq.core import read_source_epoch as epoch
        with patch.object(epoch, '_reads_retired', False):
            epoch.retire_process_reads()
            with self.assertRaises(epoch.SourceReadUnavailable):
                transaction = source_read()
                with transaction:
                    self.fail('original observe gate must remain refused')
            self.assertEqual(service.get_pve_read_configuration(self.cfg),
                             {'addresses': [], 'token_principal': '', 'ca_configured': False})
            self.configure()
            self.assertEqual(service.get_pve_read_configuration(self.cfg)['token_principal'], 'Observer@pve')

    def test_passive_get_refuses_while_helper_lock_is_owned(self):
        with service._LOCK:
            with self.assertRaises(service.ConfigurationError) as caught:
                service.get_pve_read_configuration(self.cfg)
        self.assertEqual(str(caught.exception), 'configuration_unavailable')
        self.assert_unchanged()


if __name__ == '__main__':
    unittest.main()
