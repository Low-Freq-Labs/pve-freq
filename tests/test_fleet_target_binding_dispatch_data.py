"""Original method routing with fictional native/TLS/gates/socket ports.

The read fixture establishes DATA, never a real live installation. Binding
uses fictional downstream constructors, while dispatch/read/frame/broker
methods execute. No original native server, source IO or activation occurs.
"""
from contextlib import contextmanager
from types import SimpleNamespace
import io
import unittest
from unittest.mock import patch

from freq.services import pilot_component_binding as binding
from freq.services import pilot_cluster_dispatch as dispatch
from freq.services import cluster_pilot_request as routing
from freq.services import pilot_fleet_targets_read as read
from test_fleet_component_retention_data import FleetComponentRetentionData
from test_original_fleet_target_read_data import OriginalFleetTargetReadData


class Control(BaseException):
    pass


class FleetTargetBindingDispatchData(unittest.TestCase):
    @contextmanager
    def fixture(self, **options):
        with OriginalFleetTargetReadData().fixture(**options) as f:
            for name, cls in (
                    ('_auth_inputs', dispatch.OriginalPilotAuthAttempts),
                    ('_login_rate', dispatch.OriginalPilotLoginRate),
                    ('_cluster_selections', dispatch.OriginalClusterSelections),
                    ('_cluster_reads', dispatch.OriginalClusterReads),
                    ('_static_responder', dispatch.OriginalPilotStatic),
                    ('_guest_reference_store', dispatch.OriginalGuestReferenceStore)):
                value = object.__new__(cls)
                value._installation = f.owner
                setattr(f.owner, name, value)
            dispatcher = dispatch.OriginalPilotDispatch(f.owner)
            f.owner._dispatcher = dispatcher
            f.dispatcher = dispatcher
            yield f

    def test_FD01_binder_retains_same_reader_before_constructor(self):
        seen = []
        def initialize(component, owner):
            self.assertIs(owner._fleet_targets_reader, component)
            seen.append(component)
            component._installation = owner
        with FleetComponentRetentionData().fixture() as f, patch.object(
                binding.OriginalPilotFleetTargets, '__init__', initialize):
            f.owner._bind_original_components()
            self.assertEqual(len(seen), 1)
            self.assertIs(f.owner._fleet_targets_reader, seen[0])
            self.assertFalse(f.owner._native_current_locked(object()))
            self.assertIs(f.owner._live, False)

    def test_FD02_constructor_memory_keeps_partial_component_and_no_retry(self):
        retained = []
        memory = MemoryError('fictional allocation loss')
        def fail(component, owner):
            self.assertIs(owner._fleet_targets_reader, component)
            retained.append(component)
            raise memory
        with FleetComponentRetentionData().fixture() as f, patch.object(
                binding.OriginalPilotFleetTargets, '__init__', fail):
            with self.assertRaises(MemoryError) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, memory)
            self.assertIs(f.owner._component_binding_errors[0], memory)
            self.assertIs(f.owner._fleet_targets_reader, retained[0])
            self.assertEqual(f.owner._components_state, 'retirement-only')
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertEqual(len(retained), 1)
            f.ports['OriginalPilotDispatch'].assert_not_called()

    def test_FD03_constructor_control_identity_retained_and_propagated(self):
        control = Control()
        def fail(component, owner):
            self.assertIs(owner._fleet_targets_reader, component)
            raise control
        with FleetComponentRetentionData().fixture() as f, patch.object(
                binding.OriginalPilotFleetTargets, '__init__', fail):
            with self.assertRaises(Control) as error:
                f.owner._bind_original_components()
            self.assertIs(error.exception, control)
            self.assertIs(type(f.owner._fleet_targets_reader), read.OriginalPilotFleetTargets)
            self.assertTrue(f.owner._admission_uncertain)

    def test_FD04_late_reader_substitution_refuses_binding(self):
        with FleetComponentRetentionData().fixture() as f:
            def swap(unused):
                f.owner._fleet_targets_reader = object.__new__(read.OriginalPilotFleetTargets)
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = swap
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertEqual(f.owner._components_state, 'retirement-only')

    def test_FD05_exact_get_only_and_aliases_refuse(self):
        self.assertEqual(routing.classify_request('GET', '/api/exec/targets'),
                         ('fleet-targets', None))
        for method, target in (
                ('POST', '/api/exec/targets'), ('HEAD', '/api/exec/targets'),
                ('GET', '/api/exec/targets/'), ('GET', '/api/exec/targets?'),
                ('GET', '/api/exec/targets?view=observation'),
                ('GET', '/api/exec/%74argets'), ('GET', '//api/exec/targets'),
                ('GET', '/api/exec/run'), ('GET', '/api/fleet/exec/targets'),
                ('GET', '/api/exec/targets#x')):
            self.assertIsNone(routing.classify_request(method, target))

    def test_FD06_original_bounded_parser_classifies_empty_get_body(self):
        with self.fixture() as f:
            f.handler.rfile = io.BytesIO(b'GET /api/exec/targets HTTP/1.1\r\n'
                                        b'Host: fixture.invalid\r\n\r\n')
            self.assertTrue(f.broker._parse(f.handler, f.original))
            self.assertEqual(f.original.operation, 'fleet-targets')
            self.assertEqual(f.original.body, b'')
            self.assertEqual(f.socket.sent, [])

    def test_FD07_original_parser_refuses_get_body_before_dispatch(self):
        with self.fixture() as f:
            f.handler.rfile = io.BytesIO(b'GET /api/exec/targets HTTP/1.1\r\n'
                b'Host: fixture.invalid\r\nContent-Length: 1\r\n\r\nx')
            with self.assertRaises(dispatch._BadRequest):
                f.broker._parse(f.handler, f.original)
            self.assertEqual(f.socket.sent, [])

    def test_FD08_dispatch_executes_real_read_format_frame_once_in_model(self):
        with self.fixture() as f:
            f.dispatcher.run(f.handler)
            self.assertEqual(len(f.socket.sent), 1)
            self.assertIn(b'fleet-exec-targets-v2', f.socket.sent[0])
            self.assertEqual(f.original.fleet_targets_response.state, 'send-returned')
            with self.assertRaises(read._RequestUnavailable):
                f.dispatcher.run(f.handler)
            self.assertEqual(len(f.socket.sent), 1)

    def test_FD09_unsupported_optional_projection_fixed_refusal_no_prefix(self):
        with self.fixture(unsupported=True) as f:
            f.dispatcher.run(f.handler)
            self.assertEqual(len(f.socket.sent), 1)
            wire = f.socket.sent[0]
            self.assertTrue(wire.startswith(b'HTTP/1.1 503 '))
            self.assertEqual(wire.split(b'\r\n\r\n', 1)[1],
                             b'{"error":"fleet_exec_targets_unavailable"}')
            self.assertNotIn(b'hosts', wire)
            self.assertFalse(f.original.fleet_targets_started)

    def test_FD10_real_native_false_dispatch_can_only_refuse_success(self):
        with self.fixture() as f, patch.object(dispatch.OriginalAuthCommit,
                '_current_locked', f.real_current), patch.object(
                read, 'format_retained_fleet_targets_data') as formatter:
            f.dispatcher.run(f.handler)
            self.assertTrue(f.socket.sent[0].startswith(b'HTTP/1.1 503 '))
            formatter.assert_not_called()
            self.assertFalse(f.owner._native_current_locked(f.original))

    def test_FD11_viewer_dispatch_does_not_format_or_publish_pairs(self):
        with self.fixture(role='viewer') as f, patch.object(
                read, 'format_retained_fleet_targets_data') as formatter:
            f.dispatcher.run(f.handler)
            formatter.assert_not_called()
            self.assertTrue(f.socket.sent[0].startswith(b'HTTP/1.1 503 '))

    def test_FD12_memory_after_duty_retention_does_not_send_refusal(self):
        error = MemoryError()
        with self.fixture() as f, patch.object(read,
                'format_retained_fleet_targets_data', side_effect=error):
            with self.assertRaises(MemoryError) as raised:
                f.dispatcher.run(f.handler)
            self.assertIs(raised.exception, error)
            self.assertTrue(f.original.fleet_targets_started)
            self.assertEqual(f.original.fleet_targets_response.state, 'failed')
            self.assertEqual(f.socket.sent, [])

    def test_FD13_control_after_duty_retention_does_not_send_refusal(self):
        error = Control()
        with self.fixture() as f, patch.object(read,
                'format_retained_fleet_targets_data', side_effect=error):
            with self.assertRaises(Control) as raised:
                f.dispatcher.run(f.handler)
            self.assertIs(raised.exception, error)
            self.assertEqual(f.socket.sent, [])

    def test_FD14_original_reader_replacement_refuses_before_format_or_send(self):
        with self.fixture() as f:
            f.owner._fleet_targets_reader = object.__new__(read.OriginalPilotFleetTargets)
            f.owner._fleet_targets_reader._installation = f.owner
            with self.assertRaises(read._RequestUnavailable):
                f.dispatcher.run(f.handler)
            self.assertEqual(f.socket.sent, [])

    def test_FD15_partial_send_error_cannot_append_generic_status(self):
        with self.fixture() as f:
            def interrupted(wire):
                f.socket.sent.append(wire[:17])
                raise OSError('fictional partial send')
            f.socket.sendall = interrupted
            with self.assertRaises(read._RequestUnavailable):
                f.dispatcher.run(f.handler)
            self.assertEqual(len(f.socket.sent), 1)
            self.assertEqual(f.original.fleet_targets_response.state, 'send-attempted')

    def test_FD16_logout_during_format_cannot_publish_success(self):
        original_formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def logout(data):
                f.tokens.clear()
                return original_formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', logout):
                f.dispatcher.run(f.handler)
            self.assertEqual(len(f.socket.sent), 1)
            self.assertTrue(f.socket.sent[0].startswith(b'HTTP/1.1 503 '))
            self.assertEqual(f.original.fleet_targets_response.state, 'failed')
            self.assertIsNot(f.original.frame, f.original.fleet_targets_response.frame)

    def test_FD17_invalid_component_type_rejects_before_foreign_hooks(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError('foreign hook')
        with self.fixture() as f:
            f.owner._fleet_targets_reader = Hostile()
            with self.assertRaises(read._RequestUnavailable):
                dispatch.OriginalPilotDispatch(f.owner)
            self.assertEqual(f.socket.sent, [])

    def test_FD18_explicit_empty_is_successful_read_not_command_grant(self):
        with self.fixture(empty=True) as f:
            f.dispatcher.run(f.handler)
            wire = f.socket.sent[0]
            self.assertTrue(wire.startswith(b'HTTP/1.1 200 '))
            self.assertIn(b'"hosts":[]', wire)
            self.assertIn(b'"adoption_verified":false', wire)
            self.assertIn(b'"reachability_verified":false', wire)
            self.assertIsNone(routing.classify_request('POST', '/api/exec/run'))
