"""Fictional holder regression for repeated original startup initialization."""
import unittest
from unittest.mock import patch

from freq.services import pilot_startup_acquisition as startup
from test_startup_fleet_target_retention import StartupFleetTargetRetention


class StartupReentryRetention(unittest.TestCase):
    def fixture(self):
        return StartupFleetTargetRetention().fixture()

    def test_SR01_repeat_unstarted_or_pending_never_replaces_known_holders(self):
        for state in ('new', 'acquiring', 'failed', 'retirement-only'):
            with self.subTest(state=state), self.fixture() as f:
                before = (f.attempt._sources, f.attempt._identity, f.attempt._end,
                          f.attempt._revision, f.attempt._thread)
                f.attempt._state = state
                with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                    startup.OriginalStartupInputAttempt.__init__(
                        f.attempt, 1004, 9999.0, 'other-revision')
                self.assertEqual(f.attempt._state, state)
                after = (f.attempt._sources, f.attempt._identity, f.attempt._end,
                         f.attempt._revision, f.attempt._thread)
                self.assertTrue(all(a is b for a, b in zip(before, after)))
                f.source_ctor.assert_called_once_with(1003, 30.0)
                f.identity_ctor.assert_called_once_with(1003, 30.0)

    def test_SR02_repeat_retained_preserves_same_data_and_original_end(self):
        with self.fixture() as f:
            f.attempt.acquire()
            fleet = f.attempt.private_fleet_targets_data()
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(
                    f.attempt, 1004, 9999.0, 'replacement')
            self.assertIs(f.attempt._sources, f.source)
            self.assertIs(f.attempt._identity, f.identity)
            self.assertIs(f.attempt.private_data(), f.configured)
            self.assertIs(f.attempt.private_fleet_targets_data(), fleet)
            self.assertEqual(f.attempt._end, 30.0)
            self.assertEqual(f.attempt._state, 'retained')

    def test_SR03_repeat_retired_never_revives_or_recloses(self):
        with self.fixture() as f:
            f.attempt.acquire()
            f.attempt.retire()
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(
                    f.attempt, 1003, 30.0, 'fixture-revision')
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                f.attempt.acquire()
            self.assertEqual(f.attempt._state, 'retired')
            self.assertEqual(f.attempt._cleanup, 'locally-settled')
            self.assertIsNone(f.attempt._fleet_targets_data)
            f.source.close.assert_called_once_with()
            f.identity.close.assert_called_once_with()
            f.source_ctor.assert_called_once_with(1003, 30.0)
            f.identity_ctor.assert_called_once_with(1003, 30.0)

    def test_SR04_invalid_first_arguments_still_spend_same_initializer(self):
        obj = object.__new__(startup.OriginalStartupInputAttempt)
        with patch.object(startup, 'FixedStartupSourceReader') as source, \
                patch.object(startup, 'FixedStartupIdentityReader') as identity:
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(obj, 1003, 30.0, None)
            self.assertEqual(obj._state, 'constructing')
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(obj, 1003, 30.0, 'valid')
            source.assert_not_called()
            identity.assert_not_called()

    def test_SR05_holder_constructor_failure_cannot_be_retried(self):
        obj = object.__new__(startup.OriginalStartupInputAttempt)
        error = MemoryError('fixture-holder-allocation')
        with patch.object(startup, 'FixedStartupSourceReader', side_effect=error) as source, \
                patch.object(startup, 'FixedStartupIdentityReader') as identity:
            with self.assertRaises(MemoryError) as caught:
                startup.OriginalStartupInputAttempt.__init__(obj, 1003, 30.0, 'fixture')
            self.assertIs(caught.exception, error)
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(obj, 1003, 30.0, 'fixture')
            source.assert_called_once_with(1003, 30.0)
            identity.assert_not_called()

    def test_SR06_foreign_self_refuses_before_attributes_or_factories(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute hook')
            def __setattr__(self, name, value):
                raise AssertionError('foreign assignment hook')
        with patch.object(startup, 'FixedStartupSourceReader') as source, \
                patch.object(startup, 'FixedStartupIdentityReader') as identity:
            with self.assertRaises(startup.PilotStartupAcquisitionUnavailable):
                startup.OriginalStartupInputAttempt.__init__(Foreign(), 1003, 30.0, 'fixture')
            source.assert_not_called()
            identity.assert_not_called()
