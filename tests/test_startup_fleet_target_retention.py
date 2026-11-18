"""Original startup method with fictional readers, never native qualification."""
from contextlib import contextmanager, ExitStack
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from freq.services import pilot_startup_acquisition as startup
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_fleet_targets_data import decode_fleet_target_bytes


VALID = b'[[host]]\nlabel="fixture"\nip="192.0.2.1"\n'


class StartupFleetTargetRetention(unittest.TestCase):
    @contextmanager
    def fixture(self, hosts=VALID):
        source_bytes = (b'fixed-freq-fixture', hosts, b'vlans-fixture', b'policy-fixture')
        source = SimpleNamespace(open_fixed=Mock(), _recheck=Mock(),
            read_sources=Mock(return_value=source_bytes), close=Mock(),
            close_observations=Mock(return_value=('fixture-only',)))
        identity = SimpleNamespace(open_fixed=Mock(), _recheck=Mock(),
            read_inputs=Mock(return_value=(source_bytes[0], None, None)),
            close=Mock(), cleanup_observations=Mock(return_value=('fixture-only',)))
        configured = PilotConfiguredData('fixture-revision', (), MappingProxyType({}),
                                         'fixture-service', None, False, False)
        clock = [1.0]
        with ExitStack() as stack:
            source_ctor = stack.enter_context(patch.object(startup, 'FixedStartupSourceReader',
                                                           return_value=source))
            identity_ctor = stack.enter_context(patch.object(startup, 'FixedStartupIdentityReader',
                                                             return_value=identity))
            stack.enter_context(patch.object(startup.time, 'monotonic', side_effect=lambda: clock[0]))
            parsed = object()
            parse = stack.enter_context(patch.object(startup, 'decode_fixed_startup_inputs',
                                                     return_value=parsed))
            prepare = stack.enter_context(patch.object(startup, 'prepare_configured_cohort_data',
                                                       return_value=configured))
            attempt = startup.OriginalStartupInputAttempt(1003, 30.0, 'fixture-revision')
            yield SimpleNamespace(attempt=attempt, source=source, identity=identity,
                source_bytes=source_bytes, configured=configured, clock=clock,
                source_ctor=source_ctor, identity_ctor=identity_ctor, parse=parse,
                prepare=prepare, parsed=parsed)

    def test_ST01_same_acquired_hosts_once_and_same_retained_result(self):
        with self.fixture() as f:
            with patch.object(startup, 'decode_fleet_target_bytes',
                              wraps=decode_fleet_target_bytes) as decode:
                self.assertIs(f.attempt.acquire(), f.attempt)
                first = f.attempt.private_fleet_targets_data()
                self.assertIs(f.attempt.private_fleet_targets_data(), first)
                self.assertEqual(first.pairs, (('fixture', '192.0.2.1'),))
                decode.assert_called_once()
                self.assertIs(decode.call_args.args[0], f.source_bytes[1])
                f.source.read_sources.assert_called_once_with()
                self.assertIs(f.attempt.private_data(), f.configured)
                f.parse.assert_called_once_with(f.source_bytes, f.source_bytes[0], None, None)
                f.prepare.assert_called_once_with(f.parsed, 'fixture-revision')
                f.source_ctor.assert_called_once_with(1003, 30.0)
                f.identity_ctor.assert_called_once_with(1003, 30.0)

    def test_ST02_unsupported_fleet_does_not_change_cluster_data(self):
        with self.fixture(b'# missing host collection\n') as f:
            f.attempt.acquire()
            self.assertIs(f.attempt.private_data(), f.configured)
            self.assertEqual(f.attempt._state, 'retained')
            self.assertIsNone(f.attempt._fleet_targets_data)
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_fleet_targets_data()

    def test_ST03_explicit_empty_is_a_retained_empty_projection(self):
        with self.fixture(b'host=[]\n') as f:
            f.attempt.acquire()
            self.assertEqual(f.attempt.private_fleet_targets_data().pairs, ())

    def test_ST04_late_invalid_host_never_publishes_valid_prefix(self):
        with self.fixture(VALID + b'[[host]]\nlabel="incomplete"\n') as f:
            f.attempt.acquire()
            self.assertIsNone(f.attempt._fleet_targets_data)
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_fleet_targets_data()

    def test_ST05_expiry_after_projection_closes_both_without_publication(self):
        with self.fixture() as f:
            def decode(raw):
                result = decode_fleet_target_bytes(raw)
                f.clock[0] = 31.0
                return result
            with patch.object(startup, 'decode_fleet_target_bytes', side_effect=decode):
                with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                    f.attempt.acquire()
            self.assertIsNone(f.attempt._data)
            self.assertIsNone(f.attempt._fleet_targets_data)
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()

    def test_ST06_control_remains_original_and_both_cleanup_attempted(self):
        with self.fixture() as f:
            error = KeyboardInterrupt('fixture-control')
            f.source.close.side_effect = RuntimeError('fixture-close')
            with patch.object(startup, 'decode_fleet_target_bytes', side_effect=error):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    f.attempt.acquire()
            self.assertIs(caught.exception, error)
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()
            self.assertIsNone(f.attempt._fleet_targets_data)
            self.assertEqual(f.attempt._cleanup, 'uncertain')

    def test_ST07_allocation_error_is_not_treated_as_unsupported_fleet(self):
        with self.fixture() as f:
            error = MemoryError('fixture-allocation')
            with patch.object(startup, 'decode_fleet_target_bytes', side_effect=error):
                with self.assertRaises(MemoryError) as caught:
                    f.attempt.acquire()
            self.assertIs(caught.exception, error)
            self.assertIs(f.attempt._acquisition_errors[0], error)
            self.assertIsNone(f.attempt._fleet_targets_data)
            self.assertEqual(f.attempt._state, 'retired')
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()

    def test_ST08_wrong_return_type_refuses_without_successful_data(self):
        with self.fixture() as f:
            with patch.object(startup, 'decode_fleet_target_bytes', return_value=object()):
                with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                    f.attempt.acquire()
            self.assertIsNone(f.attempt._data)
            self.assertIsNone(f.attempt._fleet_targets_data)
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()

    def test_ST09_retirement_clears_both_values_and_never_recloses(self):
        with self.fixture() as f:
            f.attempt.acquire()
            f.attempt.retire()
            f.attempt.retire()
            self.assertIsNone(f.attempt._data)
            self.assertIsNone(f.attempt._fleet_targets_data)
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_fleet_targets_data()
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()

    def test_ST10_unstarted_getter_and_second_acquisition_never_read_again(self):
        with self.fixture() as f:
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_fleet_targets_data()
            f.source._recheck.assert_not_called()
            f.attempt.acquire()
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.acquire()
            f.source.read_sources.assert_called_once_with()

    def test_ST11_later_unsupported_attempt_does_not_reuse_prior_pairs(self):
        with self.fixture() as f:
            f.attempt.acquire()
            prior = f.attempt.private_fleet_targets_data()
            f.attempt.retire()
        with self.fixture(b'# no host collection\n') as f:
            f.attempt.acquire()
            self.assertIsNone(f.attempt._fleet_targets_data)
            self.assertEqual(prior.pairs, (('fixture', '192.0.2.1'),))
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_fleet_targets_data()

    def test_ST12_wrong_thread_refuses_before_native_diagnostics(self):
        with self.fixture() as f:
            f.attempt.acquire()
            before = f.source._recheck.call_count
            with patch.object(startup.threading, 'current_thread', return_value=object()):
                with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                    f.attempt.private_fleet_targets_data()
            self.assertEqual(f.source._recheck.call_count, before)
