"""UNRUN fictional logical-retire cross-entry faults, no original authority.

The 31-item holder below is deliberately incomplete fictional DATA for private
holder helpers only. It cannot pass original custody/guard/admission entry.
Existing saved21/16 fixture ports are patched; no native or physical owner.
"""
import unittest
from unittest.mock import patch
from test_guest_profile_begin_retirement_data import ProfileBeginRetirementData
from freq.services import pilot_guest_profile_record_retirement as once
from freq.services import pilot_guest_profile_retirement as registered
from freq.services import pilot_guest_profile_begin_retirement as saved
from freq.services import pilot_guest_profile_registration as registration


class ProfileRecordRetirementOnceData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileBeginRetirementData()
        self.f.setUp()
        self.begin,self.record=self.f.begin,self.f.record
        self.duty=registration._ProfileAcquisitionDuty.__new__(registration._ProfileAcquisitionDuty)
        self.duty.original=self.begin.original
        self.duty.begin=self.begin
        self.duty.slots=tuple(registration._ProfileSectionSlot(s)for s in registration._SECTIONS)
        self.duty.custody=registration._ProfileRetirementCustody.__new__(registration._ProfileRetirementCustody)
        items=[None]*31  # Fictional private DATA, never complete original custody.
        items[7],items[14],items[26]=self.duty.original,self.duty,self.duty.slots
        items[15],items[16]=self.begin,self.record  # Known captured logical identities only.
        object.__setattr__(self.duty.custody,'items',tuple(items))
        self.calls=[]
        self.original_retire=once._GuestReferenceRecord._retire

    def prepare(self):
        self.f.prepare()
        self.record._spent=True

    def counted_retire(self,record):
        self.calls.append(record)
        self.original_retire(record)

    def assert_sections_visited(self):
        self.assertEqual([s.cleanup for s in self.duty.slots],['returned-no-attempt']*3)

    def test_RO01_registered_then_saved_begin_calls_same_record_once(self):
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            self.assertIsNone(registered._retire_profile_holders_data(self.duty,None))
            outer=self.f.retire()
        self.assertEqual(self.calls,[self.record])
        self.assertEqual(outer.record_retirement,'call-returned')
        self.assertEqual(self.begin.record_once_state,'call-returned')
        self.assert_sections_visited()

    def test_RO02_saved_begin_then_registered_calls_same_record_once(self):
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            self.f.retire()
            self.assertIsNone(registered._retire_profile_holders_data(self.duty,None))
        self.assertEqual(self.calls,[self.record])
        self.assert_sections_visited()

    def test_RO03_registered_lost_record_return_keeps_memory_and_still_visits_slots(self):
        error=MemoryError()
        def lost(record):
            self.calls.append(record)
            record._retired=True
            raise error
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',lost):
            self.prepare()
            self.assertIs(registered._retire_profile_holders_data(self.duty,None),error)
            with self.assertRaises(MemoryError)as caught:self.f.retire()
        self.assertIs(caught.exception,error)
        self.assertEqual(self.calls,[self.record])
        self.assertEqual(self.begin.record_once_state,'call-pending')
        self.assertIs(self.begin.record_once_error,error)
        self.assert_sections_visited()

    def test_RO04_saved_lost_return_keeps_control_while_registered_visits_slots(self):
        error=KeyboardInterrupt()
        def lost(record):
            self.calls.append(record)
            record._retired=True
            raise error
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',lost):
            self.prepare()
            with self.assertRaises(KeyboardInterrupt):self.f.retire()
            self.assertIs(registered._retire_profile_holders_data(self.duty,None),error)
        self.assertEqual(self.calls,[self.record])
        self.assert_sections_visited()

    def test_RO05_late_guard_failure_is_not_settled_by_inner_known_return(self):
        error=MemoryError()
        self.f.locks[3].release_error=error
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            with self.assertRaises(MemoryError):self.f.retire()
            self.assertEqual(self.begin.record_once_state,'call-returned')
            self.assertIs(registered._retire_profile_holders_data(self.duty,None),error)
        self.assertEqual(self.calls,[self.record])
        self.assert_sections_visited()
        self.assertEqual(self.begin.cleanup_retirement.phase,'uncertain')

    def test_RO06_legacy_unstarted_helper_also_uses_same_once_record(self):
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            self.assertIsNone(registered._retire_unstarted_profile_holders_data(self.duty,None))
            self.assertIsNone(registered._retire_unstarted_profile_holders_data(self.duty,None))
            self.f.retire()
        self.assertEqual(self.calls,[self.record])

    def test_RO07_pending_without_caught_error_never_retries_from_retired_flag(self):
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            self.begin.record_once,self.begin.record_once_state=self.record,'call-pending'
            self.record._retired=True
            error=registered._retire_profile_holders_data(self.duty,None)
        self.assertIsInstance(error,once._RequestUnavailable)
        self.assertEqual(self.calls,[])
        self.assert_sections_visited()

    def test_RO08_pending_outer_constructor_blocks_record_but_not_known_sections(self):
        with self.f.ports(),patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            self.prepare()
            self.begin.cleanup_retirement_capture='constructor-pending'
            error=registered._retire_profile_holders_data(self.duty,None)
        self.assertIsInstance(error,once._RequestUnavailable)
        self.assertEqual(self.calls,[])
        self.assert_sections_visited()

    def test_RO09_foreign_begin_or_record_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign hook')
        with self.assertRaises(once._RequestUnavailable):once._retire_profile_record_once_data(Trap(),self.record)
        with self.assertRaises(once._RequestUnavailable):once._retire_profile_record_once_data(self.begin,Trap())
        self.assertEqual(self.begin.record_once_state,'unattempted')

    def test_RO10_known_return_cannot_adopt_other_record_or_reconstruct_receipt(self):
        with patch.object(once._GuestReferenceRecord,'_retire',self.counted_retire):
            once._retire_profile_record_once_data(self.begin,self.record)
            other=once._GuestReferenceRecord.__new__(once._GuestReferenceRecord)
            with self.assertRaises(once._RequestUnavailable):once._retire_profile_record_once_data(self.begin,other)
        self.assertEqual(self.calls,[self.record])
        self.assertIs(self.begin.record_once,self.record)

    def test_RO11_earlier_control_survives_later_distinct_cleanup_control(self):
        first,later=KeyboardInterrupt(),SystemExit()
        with self.f.ports():
            self.prepare()
            self.begin.record_once=self.record
            self.begin.record_once_state='call-pending'
            self.begin.record_once_error=later
            self.assertIs(registered._retire_profile_holders_data(self.duty,first),first)
        self.assertIs(self.begin.record_once_error,later)
        self.assert_sections_visited()

    def test_RO12_none_ledger_fields_never_replace_retained_ordinary_failure(self):
        error=ValueError('fictional ordinary')
        with self.f.ports():
            self.prepare()
            previous=saved._ProfileBeginRetirementDuty(self.begin)
            previous.phase='uncertain'
            previous.primary=error
            self.begin.cleanup_retirement=previous
            self.begin.cleanup_retirement_capture='constructor-returned'
            self.assertIs(registered._retire_profile_holders_data(self.duty,None),error)
        self.assert_sections_visited()
