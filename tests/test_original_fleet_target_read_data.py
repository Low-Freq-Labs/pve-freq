"""Original method orchestration with fictional TLS/native and socket ports.

No successful original native owner is constructed. One test restores the real
auth currentness method and proves the unchanged native-current False refusal.
"""
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace, MappingProxyType
import json
import threading
import unittest
from unittest.mock import patch, Mock

from freq.api import auth
from freq.services import pilot_fleet_targets_read as read
from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_startup_acquisition import OriginalStartupInputAttempt
from freq.services.pilot_fleet_targets_data import decode_fleet_target_bytes, ConfiguredFleetTargetsData
from freq.services.pilot_auth_commit import OriginalAuthCommit
from freq.services.cluster_references import ClusterReferences


class FictionalGate:
    def __init__(self):
        self.acquisitions = self.releases = 0
        self.owned = False
        self.acquire_fault = self.release_fault = None

    def acquire(self, **kwargs):
        self.acquisitions += 1
        if self.acquire_fault and self.acquisitions == self.acquire_fault[0]:
            raise self.acquire_fault[1]
        if self.owned:
            raise AssertionError('fictional gate double acquisition')
        self.owned = True
        return True

    def release(self):
        self.releases += 1
        if self.release_fault and self.releases == self.release_fault[0]:
            raise self.release_fault[1]
        if not self.owned:
            raise AssertionError('fictional gate unowned release')
        self.owned = False


class FictionalSocket:
    def __init__(self):
        self.sent, self.timeouts = [], []

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, value):
        self.sent.append(value)


class OriginalFleetTargetReadData(unittest.TestCase):
    @contextmanager
    def fixture(self, *, role='admin', unsupported=False, empty=False):
        owner = OriginalPilotInstallation()
        owner._live, owner._admission_uncertain = True, False
        gates = [FictionalGate() for _ in range(4)]
        owner._gate = gates[0]
        owner._references = object.__new__(ClusterReferences)
        owner._references._lock = gates[2]
        server = object.__new__(read._OriginalPilotServer)
        broker = object.__new__(read._OriginalHTTPRequests)
        server._cluster_pilot_installation, server._pilot_requests = owner, broker
        broker._server, broker._gate = server, gates[3]
        broker._live, broker._gate_uncertain = True, False
        owner._server = server
        owner._auth_commit = OriginalAuthCommit(owner)
        session = dict(user='fixture-admin', role=role, ts=999.0,
                       last_activity_ts=999.0, csrf_token='fixture-csrf')
        tokens = {'fixture-token': session}
        owner._issued_sessions = {'fixture-token': session}
        config = PilotConfiguredData('fixture-revision', (),
            MappingProxyType({'fixture-admin': role}), 'fixture-service',
            ('fixture@pve', 'configured'), True, True)
        startup = object.__new__(OriginalStartupInputAttempt)
        startup._state, startup._data = 'retained', config
        projection = None if unsupported else decode_fleet_target_bytes(
            b'host=[]' if empty else b'[[host]]\nlabel="fixture"\nip="192.0.2.7"')
        startup._fleet_targets_data = projection
        owner._startup_inputs, owner._configured_data = startup, config
        owner._configured_fleet_targets_data = projection
        for field, value in (('_configuration_revision', config.configuration_revision),
                             ('_configured_nodes', config.nodes), ('_configured_roles', config.roles),
                             ('_service_user', config.service_user), ('_configured_token_id', config.token_id),
                             ('_config_supported', config.config_supported), ('_policy_supported', config.policy_supported)):
            setattr(owner, field, value)
        socket = FictionalSocket()
        original = read._OriginalRequest(socket, 140.0, '192.0.2.99')
        original.write_end, original.thread = 130.0, threading.current_thread()
        original.phase, original.operation = 'ready', 'fleet-targets'
        handler = object.__new__(read._OriginalPilotHandler)
        handler.request, handler.server, handler.headers = socket, server, {}
        handler.close_connection = False
        original.handler = handler
        broker._requests = {socket: original}
        component = object.__new__(read.OriginalPilotFleetTargets)
        owner._fleet_targets_reader = component
        read.OriginalPilotFleetTargets.__init__(component, owner)
        clock = SimpleNamespace(now=100.0)
        real_current = OriginalAuthCommit._current_locked

        def fictional_native_port(transaction, request, phase):
            # Explicitly substituted native/cohort port, never production proof.
            if (transaction._installation is not owner or owner._live is not True or
                    owner._admission_uncertain or broker._live is not True or
                    request is not original or request.phase != phase or
                    not clock.now < original.end):
                raise read._RequestUnavailable()

        with ExitStack() as stack:
            stack.enter_context(patch.object(auth, '_auth_lock', gates[1]))
            stack.enter_context(patch.object(auth, '_auth_tokens', tokens))
            stack.enter_context(patch.object(auth, '_extract_session_token_and_source',
                                            return_value=('fixture-token', 'cookie')))
            tls = stack.enter_context(patch.object(auth, '_cluster_pilot_direct_tls', return_value=True))
            stack.enter_context(patch.object(OriginalAuthCommit, '_current_locked', fictional_native_port))
            stack.enter_context(patch.object(read.time, 'monotonic', side_effect=lambda: clock.now))
            stack.enter_context(patch.object(read.time, 'time', return_value=1000.0))
            yield SimpleNamespace(owner=owner, broker=broker, original=original,
                handler=handler, socket=socket, component=component, startup=startup,
                projection=projection, session=session, tokens=tokens, gates=gates,
                clock=clock, real_current=real_current, tls=tls)

    def body(self, response):
        return json.loads(response._wire.split(b'\r\n\r\n', 1)[1])

    def test_RT01_model_original_methods_admit_and_send_same_frame_once(self):
        with self.fixture() as f:
            response = f.component.admit_targets_response(f.handler)
            self.assertIs(f.original.frame, response)
            self.assertIs(f.original.fleet_targets_response.data, f.projection)
            self.assertEqual(self.body(response)['source'], 'retained_hosts_bytes')
            f.component.write_targets_response(f.handler, response)
            self.assertEqual(f.socket.sent, [response._wire])
            self.assertTrue(f.handler.close_connection)
            self.assertEqual(f.original.fleet_targets_response.state, 'send-returned')
            with self.assertRaises(read._RequestUnavailable):
                f.component.write_targets_response(f.handler, response)
            self.assertEqual(len(f.socket.sent), 1)

    def test_RT02_real_original_native_current_false_refuses_before_format(self):
        with self.fixture() as f, patch.object(OriginalAuthCommit, '_current_locked', f.real_current), \
                patch.object(read, 'format_retained_fleet_targets_data') as formatter:
            with self.assertRaises(read._RequestUnavailable):
                f.component.admit_targets_response(f.handler)
            self.assertFalse(f.owner._native_current_locked(f.original))
            self.assertIs(f.original.fleet_targets_started, False)
            formatter.assert_not_called()
            self.assertEqual(f.socket.sent, [])

    def test_RT03_viewer_session_cannot_start_admin_read(self):
        with self.fixture(role='viewer') as f:
            with self.assertRaises(read._RequestUnavailable):
                f.component.admit_targets_response(f.handler)
            self.assertIs(f.original.fleet_targets_started, False)

    def test_RT04_protected_role_uses_same_explicit_admin_hierarchy(self):
        with self.fixture(role='protected') as f:
            response = f.component.admit_targets_response(f.handler)
            self.assertEqual(self.body(response)['schema'], 'fleet-exec-targets-v2')

    def test_RT05_session_revoked_during_format_cannot_admit_response(self):
        formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def revoked(data):
                f.tokens.clear()
                return formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', side_effect=revoked):
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)
            self.assertIsNone(f.original.frame)
            self.assertEqual(f.original.fleet_targets_response.state, 'failed')

    def test_RT06_equal_replacement_data_after_format_cannot_publish(self):
        formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def changed(data):
                f.owner._configured_fleet_targets_data = ConfiguredFleetTargetsData(
                    data.pairs, data.target_set_sha256)
                return formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', side_effect=changed):
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)
            self.assertIsNone(f.original.frame)
            self.assertIs(f.original.fleet_targets_response.data, f.projection)

    def test_RT07_original_write_end_expiring_during_format_cannot_publish(self):
        formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def expired(data):
                f.clock.now = 131.0
                return formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', side_effect=expired):
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)
            self.assertIsNone(f.original.frame)

    def test_RT08_optional_unavailable_refuses_fleet_but_keeps_cluster_data(self):
        with self.fixture(unsupported=True) as f:
            with self.assertRaises(read._RequestUnavailable):
                f.component.admit_targets_response(f.handler)
            self.assertTrue(f.owner._original_configured_data_current())
            self.assertIs(f.original.fleet_targets_started, False)

    def test_RT09_explicit_empty_emits_only_complete_read_data(self):
        with self.fixture(empty=True) as f:
            doc = self.body(f.component.admit_targets_response(f.handler))
            self.assertEqual(doc['hosts'], [])
            self.assertTrue(doc['complete'])
            self.assertFalse(doc['adoption_verified'])
            self.assertFalse(doc['loader_may_bootstrap_or_migrate'])

    def test_RT10_formatter_memory_and_control_failures_keep_spent_retained_duty(self):
        for error in (MemoryError('fixture'), KeyboardInterrupt('fixture')):
            with self.subTest(kind=type(error).__name__), self.fixture() as f, \
                    patch.object(read, 'format_retained_fleet_targets_data', side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    f.component.admit_targets_response(f.handler)
                self.assertIs(caught.exception, error)
                self.assertTrue(f.original.fleet_targets_started)
                self.assertEqual(f.original.fleet_targets_response.state, 'failed')
                self.assertIsNone(f.original.frame)
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)

    def test_RT11_frame_allocation_failure_keeps_same_private_preparation(self):
        error = MemoryError('fixture-frame-allocation')
        with self.fixture() as f, patch.object(read, 'OriginalPilotResponse', side_effect=error):
            with self.assertRaises(MemoryError) as caught:
                f.component.admit_targets_response(f.handler)
            self.assertIs(caught.exception, error)
            self.assertIs(f.original.fleet_targets_response.data, f.projection)
            self.assertIsNone(f.original.frame)

    def test_RT12_equal_copied_frame_cannot_claim_original_write(self):
        with self.fixture() as f:
            response = f.component.admit_targets_response(f.handler)
            other = read.OriginalPilotResponse(200,
                response._wire.split(b'\r\n\r\n', 1)[1], 'application/json')
            with self.assertRaises(read._RequestUnavailable):
                f.component.write_targets_response(f.handler, other)
            self.assertEqual(f.original.phase, 'admitted')
            self.assertEqual(f.socket.sent, [])

    def test_RT13_revocation_between_admission_and_reserve_still_prevents_send(self):
        with self.fixture() as f:
            response = f.component.admit_targets_response(f.handler)
            f.tokens.clear()
            with self.assertRaises(read._RequestUnavailable):
                f.component.write_targets_response(f.handler, response)
            self.assertEqual(f.socket.sent, [])

    def test_RT14_same_request_never_formats_twice_and_format_runs_without_gates(self):
        formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def outside(data):
                self.assertFalse(any(g.owned for g in f.gates))
                return formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', side_effect=outside) as spy:
                response = f.component.admit_targets_response(f.handler)
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)
                f.component.write_targets_response(f.handler, response)
                spy.assert_called_once_with(f.projection)

    def test_RT15_replaced_private_duty_cannot_admit_formatted_frame(self):
        formatter = read.format_retained_fleet_targets_data
        with self.fixture() as f:
            def replaced(data):
                f.original.fleet_targets_response = object.__new__(read._FleetTargetReadDuty)
                return formatter(data)
            with patch.object(read, 'format_retained_fleet_targets_data', side_effect=replaced):
                with self.assertRaises(read._RequestUnavailable):
                    f.component.admit_targets_response(f.handler)
            self.assertIsNone(f.original.frame)

    def test_RT16_component_initialization_is_permanent_even_after_first_refusal(self):
        with self.fixture() as f:
            with self.assertRaises(read._RequestUnavailable):
                read.OriginalPilotFleetTargets.__init__(f.component, f.owner)
            other = object.__new__(read.OriginalPilotFleetTargets)
            with self.assertRaises(read._RequestUnavailable):
                read.OriginalPilotFleetTargets.__init__(other, object())
            with self.assertRaises(read._RequestUnavailable):
                read.OriginalPilotFleetTargets.__init__(other, f.owner)
            self.assertEqual(other._state, 'constructing')

    def test_RT17_foreign_handler_refuses_before_any_tls_attribute_hook(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError('foreign handler hook')
        with self.fixture() as f:
            with self.assertRaises(read._RequestUnavailable):
                f.component.admit_targets_response(Hostile())
            f.tls.assert_not_called()

    def test_RT18_unknown_final_gate_acquisition_retires_without_speculative_release(self):
        error = RuntimeError('fictional-unknown-acquire')
        with self.fixture() as f:
            f.gates[0].acquire_fault = (3, error)
            with self.assertRaises(RuntimeError) as caught:
                f.component.admit_targets_response(f.handler)
            self.assertIs(caught.exception, error)
            self.assertEqual(f.gates[0].releases, 2)
            self.assertFalse(f.owner._live)
            self.assertFalse(f.broker._live)
            self.assertTrue(f.owner._admission_uncertain)
            self.assertIsNone(f.original.frame)

    def test_RT19_release_control_after_admission_disables_every_future_send(self):
        error = KeyboardInterrupt('fictional-release-unknown')
        with self.fixture() as f:
            f.gates[3].release_fault = (3, error)
            with self.assertRaises(KeyboardInterrupt) as caught:
                f.component.admit_targets_response(f.handler)
            self.assertIs(caught.exception, error)
            self.assertEqual([g.releases for g in f.gates], [3, 3, 3, 3])
            self.assertFalse(f.owner._live)
            self.assertFalse(f.broker._live)
            self.assertEqual(f.socket.sent, [])

    def test_RT20_write_cannot_use_later_request_end_after_captured_write_expiry(self):
        with self.fixture() as f:
            response = f.component.admit_targets_response(f.handler)
            self.assertEqual(f.original.fleet_targets_response.end, 130.0)
            f.clock.now = 131.0
            with self.assertRaises(read._RequestUnavailable):
                f.component.write_targets_response(f.handler, response)
            self.assertEqual(f.socket.sent, [])
