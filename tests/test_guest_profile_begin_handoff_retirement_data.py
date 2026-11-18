"""UNRUN typed canonical response-handoff recognition with fictional ports."""
import unittest
from test_guest_profile_begin_retirement_data import ProfileBeginRetirementData
from freq.services import pilot_guest_profile_begin_retirement as source


class ProfileBeginHandoffRetirementData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileBeginRetirementData()
        self.f.setUp()
        self.original=self.f.f.original
        self.begin=self.f.begin
        self.acquisition=source._ProfileAcquisitionDuty.__new__(source._ProfileAcquisitionDuty)
        # Partial fictional publication: no plan/custody/slots/native object.
        self.acquisition.original=self.original
        self.acquisition.begin=self.begin

    def test_BH01_partial_acquisition_handoff_recognizes_saved_begin_without_31fields(self):
        with self.f.ports():
            self.f.prepare()
            self.original.guest_response=self.acquisition
            self.assertIs(source._original_retained_profile_begin_data(self.original),self.begin)
            duty=self.f.retire()
        self.assertIs(duty.record,self.f.record)
        self.assertTrue(self.f.record._retired)
        self.assertIs(self.original.guest_response,self.acquisition)
        self.assertEqual(len(self.f.events),8)
        self.assertFalse(hasattr(self.acquisition,'custody'))

    def test_BH02_other_original_acquisition_refuses_before_saved_guard_acquire(self):
        with self.f.ports():
            self.f.prepare()
            self.acquisition.original=object()
            self.original.guest_response=self.acquisition
            with self.assertRaises(source._RequestUnavailable):self.f.retire()
        self.assertFalse(self.f.record._retired)
        self.assertEqual(self.f.events,[])

    def test_BH03_foreign_begin_in_typed_handoff_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign begin')
        self.acquisition.begin=Trap()
        self.original.guest_response=self.acquisition
        with self.assertRaises(source._RequestUnavailable):
            source._original_retained_profile_begin_data(self.original)
        self.assertEqual(self.f.events,[])

    def test_BH04_mutable_positive_aliases_after_handoff_do_not_redirect_saved_record(self):
        with self.f.ports():
            self.f.prepare()
            self.original.guest_response=self.acquisition
            self.begin.record=self.begin.family=self.begin.target=object()
            self.begin.session={}
            self.begin.values=()
            self.begin.end=0.0
            duty=self.f.retire()
        self.assertIs(duty.record,self.f.record)
        self.assertTrue(self.f.record._retired)
        self.assertEqual(len(self.f.events),8)

    def test_BH05_handoff_repeated_failed_retirement_never_reruns_saved_record(self):
        error=MemoryError()
        self.f.locks[3].release_error=error
        with self.f.ports():
            self.f.prepare()
            self.original.guest_response=self.acquisition
            with self.assertRaises(MemoryError)as first:self.f.retire()
            events=tuple(self.f.events)
            with self.assertRaises(MemoryError)as second:self.f.retire()
        self.assertIs(first.exception,error)
        self.assertIs(second.exception,error)
        self.assertEqual(tuple(self.f.events),events)
        self.assertTrue(self.f.record._retired)

    def test_BH06_direct_original_begin_recognition_still_returns_exact_same_holder(self):
        self.assertIs(source._original_retained_profile_begin_data(self.original),self.begin)
