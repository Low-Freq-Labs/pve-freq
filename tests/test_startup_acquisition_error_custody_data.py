"""Original startup acquire/retire with fictional readers and allocation faults."""
import unittest
from unittest.mock import patch

from freq.services import pilot_startup_acquisition as startup
from test_startup_fleet_target_retention import StartupFleetTargetRetention


class Control(BaseException):
    pass


class StartupAcquisitionErrorCustodyData(unittest.TestCase):
    def fixture(self):
        return StartupFleetTargetRetention().fixture()

    def assert_closed_once(self, f):
        f.source.close.assert_called_once_with()
        f.identity.close.assert_called_once_with()
        self.assertEqual(f.attempt._state, 'retired')
        self.assertIsNone(f.attempt._data)
        self.assertIsNone(f.attempt._fleet_targets_data)
        self.assertEqual(f.attempt._end, 30.0)

    def test_SA01_body_memory_propagates_same_object_after_both_closes(self):
        body = MemoryError()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire()
            self.assertIs(caught.exception, body)
            self.assertIs(f.attempt._acquisition_errors[0], body)
            self.assertIs(f.attempt._acquisition_failure, body)
            self.assertEqual(f.attempt._cleanup, 'locally-settled')
            self.assert_closed_once(f)

    def test_SA02_later_close_memory_outranks_ordinary_close(self):
        ordinary, memory = OSError('fictional private close'), MemoryError()
        with self.fixture() as f:
            f.attempt.acquire()
            f.source.close.side_effect, f.identity.close.side_effect = ordinary, memory
            with self.assertRaises(MemoryError) as caught:
                f.attempt.retire()
            self.assertIs(caught.exception, memory)
            self.assertIs(f.attempt._acquisition_errors[1], ordinary)
            self.assertIs(f.attempt._acquisition_errors[2], memory)
            self.assertIs(f.attempt._acquisition_failure, memory)
            self.assertEqual(f.attempt._cleanup, 'uncertain')
            self.assert_closed_once(f)

    def test_SA03_first_body_memory_survives_later_memory_and_retains_all(self):
        body, source, identity = MemoryError(), MemoryError(), MemoryError()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            f.source.close.side_effect, f.identity.close.side_effect = source, identity
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire()
            self.assertIs(caught.exception, body)
            self.assertIs(f.attempt._acquisition_errors[0], body)
            self.assertIs(f.attempt._acquisition_errors[1], source)
            self.assertIs(f.attempt._acquisition_errors[2], identity)
            self.assertIs(f.attempt._acquisition_errors[3], source)
            self.assertIs(f.attempt._acquisition_failure, body)
            self.assert_closed_once(f)

    def test_SA04_first_cleanup_control_outranks_body_memory(self):
        body, source, identity = MemoryError(), Control(), Control()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            f.source.close.side_effect, f.identity.close.side_effect = source, identity
            with self.assertRaises(Control) as caught:
                f.attempt.acquire()
            self.assertIs(caught.exception, source)
            self.assertIs(f.attempt._acquisition_errors[0], body)
            self.assertIs(f.attempt._acquisition_errors[1], source)
            self.assertIs(f.attempt._acquisition_errors[2], identity)
            self.assertIs(f.attempt._acquisition_failure, source)
            self.assert_closed_once(f)

    def test_SA05_body_control_survives_later_control_and_memory(self):
        body, source, identity = Control(), MemoryError(), Control()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            f.source.close.side_effect, f.identity.close.side_effect = source, identity
            with self.assertRaises(Control) as caught:
                f.attempt.acquire()
            self.assertIs(caught.exception, body)
            self.assertIs(f.attempt._acquisition_errors[1], source)
            self.assertIs(f.attempt._acquisition_errors[2], identity)
            self.assertIs(f.attempt._acquisition_failure, body)
            self.assert_closed_once(f)

    def test_SA06_ordinary_public_refusal_keeps_private_body_and_closes(self):
        body, source, identity = ValueError('fictional private body'), OSError(), ValueError()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            f.source.close.side_effect, f.identity.close.side_effect = source, identity
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable) as caught:
                f.attempt.acquire()
            self.assertEqual(str(caught.exception), 'Pilot startup acquisition unavailable')
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertIs(f.attempt._acquisition_errors[0], body)
            self.assertIs(f.attempt._acquisition_errors[1], source)
            self.assertIs(f.attempt._acquisition_errors[2], identity)
            self.assertIs(f.attempt._acquisition_failure, body)
            self.assert_closed_once(f)

    def test_SA07_repeat_after_uncertainty_keeps_ledger_end_and_no_reclose(self):
        body, close = MemoryError(), OSError()
        with self.fixture() as f, patch.object(startup, 'decode_fleet_target_bytes', side_effect=body):
            f.source.close.side_effect = close
            with self.assertRaises(MemoryError):
                f.attempt.acquire()
            errors = f.attempt._acquisition_errors
            before = list(errors)
            with self.assertRaises(startup.PilotStartupAcquisitionClosureUncertain):
                f.attempt.retire()
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(f.attempt, 1003, 9999.0, 'other')
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.acquire()
            self.assertIs(f.attempt._acquisition_errors, errors)
            self.assertEqual(errors, before)
            self.assertIs(f.attempt._acquisition_failure, body)
            f.source_ctor.assert_called_once_with(1003, 30.0)
            f.identity_ctor.assert_called_once_with(1003, 30.0)
            self.assert_closed_once(f)

    def test_SA08_successful_retirement_has_empty_ledger_and_no_renewal(self):
        with self.fixture() as f:
            errors = f.attempt._acquisition_errors
            f.attempt.acquire()
            f.attempt.retire()
            f.attempt.retire()
            self.assertIs(f.attempt._acquisition_errors, errors)
            self.assertEqual(errors, [None] * 4)
            self.assertIsNone(f.attempt._acquisition_failure)
            self.assertEqual(f.attempt._cleanup, 'locally-settled')
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.private_data()
            self.assert_closed_once(f)
