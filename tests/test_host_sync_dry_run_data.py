"""Whole original host-sync function over explicit fictional effect ports.

Only the selected function definition is compiled from the pinned source;
application imports/initializers and the actual boundary writer never run.
"""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch


_SOURCE = Path(__file__).resolve().parents[1] / 'freq/modules/hosts.py'


class HostSyncDryRunData(unittest.TestCase):
    @contextmanager
    def fixture(self, *, existing=False, node=False, physical=False):
        events = []
        address = '192.0.2.7'
        host = SimpleNamespace(ip=address, label='fixture', htype='pve' if node else 'linux',
            groups='', vmid=0, all_ips=[], managed=True)
        cfg = SimpleNamespace(hosts=[host] if existing else [],
            pve_nodes=[address] if node else [], pve_node_names=['fixture'] if node else [],
            ssh_key_path='/fictional/key',
            fleet_boundaries=SimpleNamespace(physical={}))
        if physical:
            cfg.fleet_boundaries.physical['fixture'] = SimpleNamespace(
                ip=address, label='fixture', device_type='truenas', groups='', scope='core')
        colors = SimpleNamespace(**{k: '' for k in ['GREEN', 'YELLOW', 'RED', 'DIM', 'RESET', 'BOLD']})
        fmt = SimpleNamespace(C=colors)
        for name in ['header', 'blank', 'step_ok', 'step_warn', 'step_start', 'line', 'footer']:
            setattr(fmt, name, lambda *unused: None)
        def discovery(**kwargs):
            events.append(('fictional-ssh', kwargs['command']))
            return SimpleNamespace(returncode=1, stdout='')
        ssh = ModuleType('freq.core.ssh')
        ssh.run = discovery
        def persist(owner, discovered):
            events.append(('boundary-helper', owner, discovered))
        def unexpected(*unused, **kwargs):
            raise AssertionError('unexpected persistence port')
        namespace = {'FreqConfig': SimpleNamespace, 'json': json, 'fmt': fmt,
            'logger': SimpleNamespace(info=lambda *unused: None),
            'HOSTS_PVE_TIMEOUT': 15, 'HOSTS_AGENT_TIMEOUT': 10,
            '_auto_populate_fleet_boundaries': persist,
            'os': SimpleNamespace(path=SimpleNamespace(isfile=unexpected)),
            'shutil': SimpleNamespace(copy2=unexpected), 'open': unexpected}
        tree = ast.parse(_SOURCE.read_bytes(), filename=str(_SOURCE))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_hosts_sync')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(_SOURCE), 'exec'), namespace)
        with patch.dict(sys.modules, {'freq.core.ssh': ssh}):
            yield SimpleNamespace(run=namespace['_hosts_sync'], cfg=cfg, host=host, events=events)

    def helper_events(self, f):
        return [event for event in f.events if event[0] == 'boundary-helper']

    def test_HS01_empty_unchanged_dry_run_never_enters_boundary_writer(self):
        with self.fixture() as f:
            self.assertEqual(f.run(f.cfg, dry_run=True), 0)
            self.assertEqual(f.events, [])

    def test_HS02_empty_unchanged_apply_retains_existing_helper_call(self):
        with self.fixture() as f:
            self.assertEqual(f.run(f.cfg, dry_run=False), 0)
            self.assertEqual(len(self.helper_events(f)), 1)
            self.assertIs(self.helper_events(f)[0][1], f.cfg)
            self.assertEqual(self.helper_events(f)[0][2], {})

    def test_HS03_manual_unchanged_dry_run_preserves_registry_without_writer(self):
        with self.fixture(existing=True) as f:
            original = f.cfg.hosts
            self.assertEqual(f.run(f.cfg, dry_run=True), 0)
            self.assertEqual(self.helper_events(f), [])
            self.assertIs(f.cfg.hosts, original)
            self.assertIs(f.cfg.hosts[0], f.host)

    def test_HS04_manual_unchanged_apply_keeps_same_original_helper_data(self):
        with self.fixture(existing=True) as f:
            original = f.cfg.hosts
            self.assertEqual(f.run(f.cfg, dry_run=False), 0)
            helper = self.helper_events(f)
            self.assertEqual(len(helper), 1)
            self.assertEqual(helper[0][2]['192.0.2.7']['source'], 'manual')
            self.assertIs(f.cfg.hosts, original)

    def test_HS05_changed_dry_run_keeps_existing_early_no_write_return(self):
        with self.fixture(physical=True) as f:
            self.assertEqual(f.run(f.cfg, dry_run=True), 0)
            self.assertEqual(self.helper_events(f), [])
            self.assertEqual(f.cfg.hosts, [])

    def test_HS06_incomplete_discovery_dry_run_retains_failure_and_skips_writer(self):
        with self.fixture(existing=True, node=True) as f:
            original = f.cfg.hosts
            self.assertEqual(f.run(f.cfg, dry_run=True), 1)
            self.assertEqual(len([e for e in f.events if e[0] == 'fictional-ssh']), 2)
            self.assertEqual(self.helper_events(f), [])
            self.assertIs(f.cfg.hosts, original)
