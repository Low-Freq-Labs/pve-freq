"""Actual registered route and dispatcher tests with in-memory HTTP streams.

These tests do not start a socket server or prove browser/network integration.
"""
from email.message import Message
import io
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.api import auth
from freq.modules.serve import FreqHandler
from freq.services.cluster_service import SuppliedClusterService


class ClusterRouteTests(unittest.TestCase):
    def setUp(self):
        self.token = 'offline-cluster-session'
        self.session = dict(user='fixture', role='viewer', ts=time.time(),
                            last_activity_ts=time.time(), csrf_token='fixture-csrf')
        with auth._auth_lock:
            self.previous = auth._auth_tokens.get(self.token)
            auth._auth_tokens[self.token] = self.session
        self.calls = []
        def source(target, deadline):
            self.calls.append(target)
            return b'[{"id":"node/a","name":"node-a","type":"node","online":1}]'
        self.service = SuppliedClusterService({'node-a': 'fixture.invalid'}, source)

    def tearDown(self):
        with auth._auth_lock:
            auth._auth_tokens.pop(self.token, None)
            if self.previous is not None:
                auth._auth_tokens[self.token] = self.previous

    def handler(self, path, data, *, csrf=True):
        handler = object.__new__(FreqHandler)
        handler.command, handler.path = 'POST', path
        handler._request_id = 'offline-fixture'
        handler.headers = Message()
        raw = json.dumps(data, separators=(',', ':')).encode()
        handler.headers['Content-Type'] = 'application/json'
        handler.headers['Content-Length'] = str(len(raw))
        handler.headers['Cookie'] = 'freq_session=' + self.token
        if csrf:
            handler.headers['X-Freq-CSRF'] = 'fixture-csrf'
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.server = SimpleNamespace(cluster_report_service=self.service)
        handler.connection = SimpleNamespace(settimeout=lambda seconds: None)
        handler.statuses, handler.sent_headers = [], []
        handler.send_response = handler.statuses.append
        handler.send_header = lambda key, value: handler.sent_headers.append((key, value))
        handler.end_headers = lambda: None
        handler.close_connection = False
        return handler

    def selection(self):
        rows = [{'name': 'node-a', 'ip': 'fixture.invalid'}]
        decorated = self.service.decorate_inventory(self.session, rows)
        self.assertNotIn('cluster_report_selection_ref', rows[0])
        return decorated[0]['cluster_report_selection_ref']

    def bound(self):
        handler = self.handler('/api/pve/cluster-report/bind', {'selection_ref': self.selection()})
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(self.calls, [])
        return json.loads(handler.wfile.getvalue())['binding_ref']

    def test_actual_registered_bind_and_read(self):
        binding = self.bound()
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        result = json.loads(handler.wfile.getvalue())
        self.assertEqual(result['schema'], 'cluster-status-browser-v1')
        self.assertEqual(result['evidence'], 'supplied_only')
        self.assertTrue(all(value is False for value in result['capabilities'].values()))
        self.assertEqual(len(result['nodes']), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(handler.close_connection)

    def test_consumed_reference_cannot_acquire_twice(self):
        binding = self.bound()
        first = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        first._dispatch()
        second = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        second._dispatch()
        self.assertEqual(second.statuses, [409])
        self.assertEqual(len(self.calls), 1)

    def test_actual_dispatch_csrf_gate_precedes_acquisition(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()}, csrf=False)
        handler._dispatch()
        self.assertEqual(handler.statuses, [403])
        self.assertEqual(self.calls, [])

    def test_session_replaced_during_source_refuses_publication(self):
        def source(target, deadline):
            with auth._auth_lock:
                auth._auth_tokens[self.token] = dict(self.session)
            return b'[]'
        self.service._reader = source
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        handler._dispatch()
        self.assertEqual(handler.statuses, [409])
        self.assertEqual(json.loads(handler.wfile.getvalue()), {'error': 'cluster_report_unavailable'})

    def test_configuration_replaced_during_source_refuses_publication(self):
        def source(target, deadline):
            self.service.replace_configuration({'node-a': 'different.invalid'})
            return b'[]'
        self.service._reader = source
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        handler._dispatch()
        self.assertEqual(handler.statuses, [409])

    def test_partial_writer_failure_has_no_second_status(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        class FailingOutput:
            def write(self, body):
                raise OSError('fictional interrupted output')
            def flush(self):
                raise AssertionError('must not flush after failed write')
        handler.wfile = FailingOutput()
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertTrue(handler._cluster_response_consumed)
        self.assertTrue(handler.close_connection)

    def test_actual_outer_dispatch_consumed_guard(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': '0' * 32})
        def failure(request):
            request._cluster_response_consumed = True
            request.send_response(200)
            raise RuntimeError('after original response attempt')
        with patch.object(FreqHandler, '_load_routes', return_value={handler.path: failure}):
            handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(handler.wfile.getvalue(), b'')
        self.assertTrue(handler.close_connection)

    def test_duplicate_request_member_refused(self):
        handler = self.handler('/api/pve/cluster-report/read', {})
        raw = b'{"binding_ref":"' + b'a' * 32 + b'","binding_ref":"' + b'b' * 32 + b'"}'
        handler.headers.replace_header('Content-Length', str(len(raw)))
        handler.rfile = io.BytesIO(raw)
        handler._dispatch()
        self.assertEqual(handler.statuses, [400])
        self.assertEqual(self.calls, [])

    def test_socket_write_does_not_hold_auth_or_configuration_mutex(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        checks = []
        service = self.service
        class LockCheckingOutput(io.BytesIO):
            def write(self, body):
                for lock in (auth._auth_lock, service.lock):
                    acquired = lock.acquire(blocking=False)
                    checks.append(acquired)
                    if acquired:
                        lock.release()
                return super().write(body)
        handler.wfile = LockCheckingOutput()
        handler._dispatch()
        self.assertEqual(checks, [True, True])
        self.assertEqual(json.loads(handler.wfile.getvalue())['schema'], 'cluster-status-browser-v1')

    def test_uninstalled_source_has_no_fallback(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        del handler.server.cluster_report_service
        handler._dispatch()
        self.assertEqual(handler.statuses, [503])
        self.assertEqual(self.calls, [])

    def test_partial_body_cannot_extend_absolute_budget(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        class PartialBody:
            def read1(self, size):
                return b'{'
        handler.rfile = PartialBody()
        with patch('freq.services.cluster_http.time.monotonic', side_effect=[0.0, 0.1, 11.0, 11.1]):
            handler._dispatch()
        self.assertEqual(handler.statuses, [])
        self.assertEqual(self.calls, [])
        self.assertTrue(handler.close_connection)

    def test_actual_inventory_publisher_copies_session_references(self):
        from freq.api import fleet
        cached = {'pve_nodes': [{'name': 'node-a', 'ip': 'fixture.invalid', 'state': 'unknown'}],
                  'fleet_state': 'unknown'}
        handler = self.handler('/api/fleet/overview', {})
        handler.command = 'GET'
        with patch.object(fleet, '_bg_cache', {'fleet_overview': cached}), \
                patch.object(fleet, '_bg_cache_ts', {'fleet_overview': time.time()}), \
                patch.object(fleet, '_bg_cache_errors', {}):
            handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        output = json.loads(handler.wfile.getvalue())
        self.assertNotIn('cluster_report_selection_ref', cached['pve_nodes'][0])
        reference = output['pve_nodes'][0]['cluster_report_selection_ref']
        self.assertEqual(len(reference), 32)
        binding, _, _ = self.service.bind(self.session, reference)
        self.assertEqual(len(binding), 32)

    def test_body_prefix_failure_never_appends_error_response(self):
        binding = self.bound()
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        class PrefixThenFailure:
            def __init__(self):
                self.prefix = b''
                self.write_calls = 0
                self.flush_calls = 0
            def write(self, body):
                self.write_calls += 1
                self.prefix += body[:17]
                raise OSError('fictional failure after accepting body prefix')
            def flush(self):
                self.flush_calls += 1
        output = PrefixThenFailure()
        handler.wfile = output
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(output.write_calls, 1)
        self.assertEqual(output.flush_calls, 0)
        self.assertEqual(len(output.prefix), 17)
        self.assertTrue(handler._cluster_response_consumed)
        self.assertTrue(handler.close_connection)
        self.assertEqual(len(self.calls), 1)
        reused = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        reused._dispatch()
        self.assertEqual(reused.statuses, [409])
        self.assertEqual(len(self.calls), 1)

    def test_header_callback_failure_never_starts_body_or_second_status(self):
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': self.bound()})
        header_calls = []
        def failing_header(key, value):
            header_calls.append(key)
            if key == 'Content-Length':
                raise OSError('fictional header callback failure')
        handler.send_header = failing_header
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(header_calls, ['Content-Type', 'Content-Length'])
        self.assertEqual(handler.wfile.getvalue(), b'')
        self.assertTrue(handler._cluster_response_consumed)
        self.assertTrue(handler.close_connection)
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_content_length_refused_before_body_or_acquisition(self):
        binding = self.bound()
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        handler.headers['Content-Length'] = handler.headers['Content-Length']
        class ForbiddenBody:
            def read1(self, size):
                raise AssertionError('ambiguous framing must not read body')
        handler.rfile = ForbiddenBody()
        handler._dispatch()
        self.assertEqual(handler.statuses, [400])
        self.assertEqual(json.loads(handler.wfile.getvalue()), {'error': 'cluster_report_unavailable'})
        self.assertTrue(handler.close_connection)
        self.assertEqual(self.calls, [])
        valid = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        valid._dispatch()
        self.assertEqual(valid.statuses, [200])
        self.assertEqual(len(self.calls), 1)

    def test_transfer_encoding_with_length_refused_before_body_or_acquisition(self):
        binding = self.bound()
        handler = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        handler.headers['Transfer-Encoding'] = 'chunked'
        class ForbiddenBody:
            def read1(self, size):
                raise AssertionError('conflicting framing must not read body')
        handler.rfile = ForbiddenBody()
        handler._dispatch()
        self.assertEqual(handler.statuses, [400])
        self.assertEqual(json.loads(handler.wfile.getvalue()), {'error': 'cluster_report_unavailable'})
        self.assertTrue(handler.close_connection)
        self.assertEqual(self.calls, [])
        valid = self.handler('/api/pve/cluster-report/read', {'binding_ref': binding})
        valid._dispatch()
        self.assertEqual(valid.statuses, [200])
        self.assertEqual(len(self.calls), 1)

    def test_route_module_import_does_not_bootstrap_configuration(self):
        import importlib
        from freq.api import auto
        with patch('freq.core.config.load_config', side_effect=AssertionError('configuration during import')):
            importlib.reload(auto)
        # Reload once more after the patch so handler globals keep the real loader.
        importlib.reload(auto)

    def test_automation_handlers_resolve_current_configuration_cache(self):
        from freq.api import auto
        from freq.jarvis import rules
        for data_dir in ('/fictional/first', '/fictional/second'):
            cfg = SimpleNamespace(conf_dir='/fictional/conf', data_dir=data_dir)
            with (patch.object(auto, 'load_config', return_value=cfg),
                  patch.object(rules, 'load_rules', return_value=[]),
                  patch.object(rules, 'rules_to_dicts', return_value=[]),
                  patch.object(rules, 'load_rule_state', return_value={}) as state,
                  patch.object(rules, 'load_alert_history', return_value=[]) as history,
                  patch.object(auto, 'json_response')):
                auto.handle_rules(object())
                auto.handle_rules_history(object())
                state.assert_called_once_with(data_dir + '/cache')
                history.assert_called_once_with(data_dir + '/cache')
