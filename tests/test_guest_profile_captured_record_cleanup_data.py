"""Fictional captured31 record identity cleanup; original owner port patched."""
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch
from test_guest_profile_section_slot_data import ProfileSectionSlotData
from freq.services import pilot_guest_profile_retirement as source
from freq.services import pilot_guest_profile_registration as registration

class ProfileCapturedRecordCleanupData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileSectionSlotData();self.f.setUp();self.duty=self.f.duty
        self.begin=self.duty.begin;self.record=self.begin.record
        self.owner=self.f.fixture.owner;self.store=self.f.fixture.store
    def retire(self):return source._retire_profile_holders_data(self.duty,None)
    def replace_begin_aliases(self):
        self.hooks=[];hooks=self.hooks
        class Trap:
            def __getattribute__(self,name):hooks.append(name);raise AssertionError('positive alias hook')
        self.replacement=Trap()
        for n in('record','family','source','target','cohort','generation','session','values','guest_ref'):
            setattr(self.begin,n,self.replacement)
    def graph(self):
        self.handler=source._OriginalPilotHandler.__new__(source._OriginalPilotHandler)
        server=source._OriginalPilotServer.__new__(source._OriginalPilotServer)
        broker=source._OriginalHTTPRequests.__new__(source._OriginalHTTPRequests)
        original=self.duty.original;socket=object()
        original.socket,original.handler,original.thread=socket,self.handler,threading.current_thread()
        self.handler.request,self.handler.server=socket,server
        broker._server,broker._requests,broker._gate=server,{socket:original},threading.Lock()
        server._pilot_requests=broker;self.owner._server=server;self.owner._gate=threading.Lock()
        self.store._broker=broker;self.store._references=SimpleNamespace(_lock=threading.Lock())
        self.owner._original_guest_capacity=self.owner._guest_capacity
        names=('_auth_attempts','_asset_attempts','_issued_sessions','_read_attempts',
               '_native_read_attempts','_guest_families_by_nonce','_guest_families_by_ref','_guest_reference_records')
        for name,table in zip(names,self.duty.component_tables):setattr(self.owner,name,table)
        self.duty.custody=registration._ProfileRetirementCustody(self.store,original,self.handler,self.duty)

    def test_CR01_same_captured_record_and_all_known_slots_retire(self):
        self.assertIs(source._captured_profile_cleanup_record_data(self.duty),self.record)
        self.assertIsNone(self.retire());self.assertTrue(self.record._retired)
        self.assertEqual([s.cleanup for s in self.duty.slots],['returned-no-attempt']*3)

    def test_CR02_mutated_positive_begin_aliases_never_bar_or_redirect_retirement(self):
        charge=self.record._ticket._remaining;self.replace_begin_aliases()
        self.assertIsNone(self.retire());self.assertTrue(self.record._retired)
        self.assertIs(self.begin.record,self.replacement);self.assertEqual(self.hooks,[])
        self.assertEqual(self.record._ticket._remaining,charge)
        self.assertEqual([s.cleanup for s in self.duty.slots],['returned-no-attempt']*3)

    def test_CR03_distinct_canonical_record_alias_stays_unretired(self):
        other=source._GuestReferenceRecord.__new__(source._GuestReferenceRecord)
        for name in source._GuestReferenceRecord.__slots__:setattr(other,name,getattr(self.record,name))
        self.begin.record=other
        self.assertIsNone(self.retire());self.assertTrue(self.record._retired);self.assertFalse(other._retired)

    def test_CR04_capture_record_failure_never_skips_known_section_cleanup(self):
        error=KeyboardInterrupt()
        with patch.object(source._GuestReferenceRecord,'_retire',side_effect=error)as retire:
            self.assertIs(self.retire(),error);self.assertIs(self.retire(),error)
        self.assertEqual(retire.call_count,1)
        self.assertEqual([s.cleanup for s in self.duty.slots],['returned-no-attempt']*3)
        self.assertIs(self.begin.record_once_error,error)

    def test_CR05_lost_record_return_preserves_pending_error_after_alias_changes(self):
        error=MemoryError();calls=[]
        def lost(record):calls.append(record);record._retired=True;raise error
        with patch.object(source._GuestReferenceRecord,'_retire',lost):
            self.assertIs(self.retire(),error);self.replace_begin_aliases()
            self.assertIs(self.retire(),error)
        self.assertEqual(calls,[self.record]);self.assertEqual(self.begin.record_once_state,'call-pending')
        self.assertIs(self.begin.record_once_error,error);self.assertEqual(self.hooks,[])

    def test_CR06_legacy_unstarted_helper_uses_same_captured_record(self):
        self.replace_begin_aliases()
        self.assertIsNone(source._retire_unstarted_profile_holders_data(self.duty,None))
        self.assertTrue(self.record._retired);self.assertEqual(self.hooks,[])
        self.assertEqual([s.cleanup for s in self.duty.slots],['unattempted']*3)

    def test_CR07_foreign_record_in_custody_refuses_without_method_hooks(self):
        self.replace_begin_aliases();items=list(self.duty.custody.items);items[16]=self.replacement
        object.__setattr__(self.duty.custody,'items',tuple(items))  # Deliberate fictional corruption.
        self.assertIsInstance(self.retire(),source._RequestUnavailable)
        self.assertFalse(self.record._retired);self.assertEqual(self.hooks,[])
        self.assertEqual([s.cleanup for s in self.duty.slots],['returned-no-attempt']*3)

    def test_CR08_wrong_saved_begin_refuses_without_adopting_replacement(self):
        items=list(self.duty.custody.items);items[15]=object()
        object.__setattr__(self.duty.custody,'items',tuple(items))
        self.assertIsInstance(self.retire(),source._RequestUnavailable);self.assertFalse(self.record._retired)

    def test_CR09_complete31_predicate_uses_immutable_plan_after_begin_alias_changes(self):
        self.graph();d=self.duty;custody=d.custody
        with patch.object(source,'_owned_store',return_value=self.owner):
            self.assertIs(source._profile_retirement_custody_matches(self.store,d.original,self.handler,d),custody)
            self.replace_begin_aliases()
            self.assertIs(source._profile_retirement_custody_matches(self.store,d.original,self.handler,d),custody)
        self.assertEqual(self.hooks,[]);self.assertFalse(self.record._retired)

    def test_CR10_real_registry_identity_replacement_still_refuses_before_cleanup(self):
        self.graph();d=self.duty;d.custody.items[3]._requests[d.original.socket]=object()
        with patch.object(source,'_owned_store',return_value=self.owner):
            with self.assertRaises(source._RequestUnavailable):source._profile_retirement_custody_matches(self.store,d.original,self.handler,d)
        self.assertFalse(self.record._retired)
