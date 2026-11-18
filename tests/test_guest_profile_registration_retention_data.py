"""UNRUN fictional pure constructor retention, no original guard/native grant."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from contextlib import contextmanager
from test_guest_profile_registration_data import ProfileRegistrationData
from freq.services import pilot_guest_profile_registration as source


@contextmanager
def refusing_allocator(error):
    """Replace only module binding; leave canonical class constructor slots intact."""
    allocator = Mock(side_effect=error)
    with patch.object(source, '_ProfileAcquisitionDuty', SimpleNamespace(__new__=allocator)):
        yield allocator


class ProfileRegistrationRetentionData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileRegistrationData()
        self.f.setUp()
        self.begin=self.f.begin
        self.original=self.begin.original

    def retain(self):
        return source._retain_profile_registration_duty_data(self.begin,self.original)

    def test_RX01_same_partial_holder_retained_before_init_with_original_begin_still_current(self):
        seen=[]
        original_init=source._ProfileAcquisitionDuty.__init__
        def watched(duty,original,begin):
            seen.append(duty)
            self.assertIs(begin.registration_duty,duty)
            self.assertEqual(begin.registration_capture,'constructor-pending')
            self.assertIs(original.guest_response,begin)
            original_init(duty,original,begin)
        with patch.object(source._ProfileAcquisitionDuty,'__init__',watched):duty=self.retain()
        self.assertEqual(seen,[duty])
        self.assertIs(self.begin.registration_duty,duty)
        self.assertEqual(self.begin.registration_capture,'constructor-returned')
        self.assertIs(self.original.guest_response,self.begin)
        self.assertIsNone(duty.custody)
        self.assertEqual(len(duty.slots),3)

    def test_RX02_memory_during_init_keeps_same_partial_holder_and_error(self):
        error=MemoryError()
        seen=[]
        def fail(duty,original,begin):
            seen.append(duty)
            duty.original,duty.begin=original,begin
            raise error
        with patch.object(source._ProfileAcquisitionDuty,'__init__',fail):
            with self.assertRaises(MemoryError)as caught:self.retain()
        self.assertIs(caught.exception,error)
        self.assertIs(self.begin.registration_duty,seen[0])
        self.assertIs(self.begin.registration_error,error)
        self.assertEqual(self.begin.registration_capture,'constructor-pending')
        self.assertIs(self.original.guest_response,self.begin)

    def test_RX03_new_failure_without_holder_stays_pending_and_no_retry(self):
        error=MemoryError()
        with refusing_allocator(error)as new:
            with self.assertRaises(MemoryError)as first:self.retain()
            with self.assertRaises(MemoryError)as second:self.retain()
        self.assertIs(first.exception,error)
        self.assertIs(second.exception,error)
        self.assertEqual(new.call_count,1)
        self.assertIsNone(self.begin.registration_duty)
        self.assertEqual(self.begin.registration_capture,'constructor-pending')

    def test_RX04_known_return_refuses_second_constructor_attempt(self):
        duty=self.retain()
        with refusing_allocator(AssertionError('retry')):
            with self.assertRaises(source._RequestUnavailable):self.retain()
        self.assertIs(self.begin.registration_duty,duty)
        self.assertIs(self.original.guest_response,self.begin)

    def test_RX05_repeated_partial_failure_raises_original_error_without_redo(self):
        error=KeyboardInterrupt()
        calls=[]
        def fail(duty,original,begin):
            calls.append(duty)
            raise error
        with patch.object(source._ProfileAcquisitionDuty,'__init__',fail):
            with self.assertRaises(KeyboardInterrupt)as first:self.retain()
            with self.assertRaises(KeyboardInterrupt)as second:self.retain()
        self.assertEqual(len(calls),1)
        self.assertIs(first.exception,error)
        self.assertIs(second.exception,error)
        self.assertIs(self.begin.registration_duty,calls[0])

    def test_RX06_foreign_begin_or_original_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign hook')
        with self.assertRaises(source._RequestUnavailable):source._retain_profile_registration_duty_data(Trap(),self.original)
        with self.assertRaises(source._RequestUnavailable):source._retain_profile_registration_duty_data(self.begin,Trap())
        self.assertEqual(self.begin.registration_capture,'unattempted')

    def test_RX07_pending_without_caught_error_refuses_instead_of_reconstruction(self):
        self.begin.registration_capture='constructor-pending'
        with refusing_allocator(AssertionError('retry')):
            with self.assertRaises(source._RequestUnavailable):self.retain()
        self.assertIsNone(self.begin.registration_duty)
        self.assertIsNone(self.begin.registration_error)

    def test_RX08_constructor_prefix_changes_no_spent_guest_index_or_capacity(self):
        r=self.begin.record
        before=(r._spent,r._retired,r._last_clock,r._ticket._remaining,
                tuple(self.f.owner._guest_reference_records.items()),
                tuple(self.f.owner._guest_profile_attempts.items()),
                tuple(self.f.owner._native_guest_profile_attempts.items()))
        self.retain()
        self.assertEqual((r._spent,r._retired,r._last_clock,r._ticket._remaining,
                tuple(self.f.owner._guest_reference_records.items()),
                tuple(self.f.owner._guest_profile_attempts.items()),
                tuple(self.f.owner._native_guest_profile_attempts.items())),before)
