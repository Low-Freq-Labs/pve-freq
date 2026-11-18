"""Captured duty aliases: pure local canonical graph with original-owner port patched."""
import unittest
from unittest.mock import patch
from test_guest_profile_captured_record_cleanup_data import ProfileCapturedRecordCleanupData
from freq.services import pilot_guest_profile_retirement as retirement
from freq.services import pilot_guest_profile_section_slot as slots
from freq.services import pilot_guest_profile_registration as registration

class ProfileCapturedDutyCleanupData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileCapturedRecordCleanupData();self.f.setUp();self.f.graph()
        self.duty,self.owner,self.store=self.f.duty,self.f.owner,self.f.store
        self.original,self.record=self.duty.original,self.f.record
        self.saved_slots=self.duty.custody.items[26]
        self.active,self.native=self.duty.custody.items[23]
        self.quarantines=[];self.store._quarantine=lambda error:self.quarantines.append(error)or error
    def aliases(self):
        hooks=[];self.hooks=hooks
        class Trap:
            def __getattribute__(self,name):hooks.append(name);raise AssertionError('positive duty alias hook')
        self.trap=Trap()
        for n in('plan','end','configured_token','credential_uid','component_tables',
                 'inventory_tables','profile_tables','slots'):setattr(self.duty,n,self.trap)
    def wrapper(self):
        with patch.object(retirement,'_owned_store',return_value=self.owner):
            return retirement.retire_profile_handler_duty(self.store,self.f.handler)
    def prepare(self):return[slots._prepare_profile_section_slot_data(self.duty,i)for i in range(3)]

    def test_DC01_complete31_predicate_ignores_current_positive_duty_aliases(self):
        custody=self.duty.custody;self.aliases()
        with patch.object(retirement,'_owned_store',return_value=self.owner):
            self.assertIs(retirement._profile_retirement_custody_matches(self.store,self.original,self.f.handler,self.duty),custody)
        self.assertEqual(self.hooks,[])

    def test_DC02_original_wrapper_retires_captured_slots_and_active_row(self):
        charge=self.record._ticket._remaining;self.aliases()
        self.assertIsNone(self.wrapper());self.assertTrue(self.record._retired)
        self.assertNotIn(self.original,self.active);self.assertIs(self.native[self.original],self.duty)
        self.assertEqual([s.cleanup for s in self.saved_slots],['returned-no-attempt']*3)
        self.assertEqual(self.record._ticket._remaining,charge);self.assertEqual(self.hooks,[])
        self.assertEqual(self.quarantines,[])

    def test_DC03_foreign_current_tables_are_not_mutated_or_adopted(self):
        foreign_active,foreign_native={self.original:object()},{self.original:object()}
        before=(dict(foreign_active),dict(foreign_native))
        self.duty.profile_tables=(foreign_active,foreign_native)
        self.assertIsNone(self.wrapper())
        self.assertEqual((foreign_active,foreign_native),before);self.assertNotIn(self.original,self.active)
        self.assertIs(self.native[self.original],self.duty)

    def test_DC04_distinct_current_slot_tuple_cannot_redirect_known_cleanup(self):
        others=tuple(registration._ProfileSectionSlot(name)for name in registration._SECTIONS)
        self.duty.slots=others
        self.assertIsNone(self.wrapper())
        self.assertEqual([s.cleanup for s in self.saved_slots],['returned-no-attempt']*3)
        self.assertEqual([s.cleanup for s in others],['unattempted']*3)

    def test_DC05_prepared_known_inner_holders_close_after_all_aliases_change(self):
        self.prepare();originals=[s.saved_attempt for s in self.saved_slots];self.aliases()
        self.assertIsNone(self.wrapper())
        self.assertEqual([s.cleanup for s in self.saved_slots],['close-returned']*3)
        self.assertTrue(all(o._original_socket._closure=='returned-no-acquisition'for o in originals))
        self.assertEqual(self.hooks,[])

    def test_DC06_one_captured_slot_control_cannot_skip_later_known_slots(self):
        self.prepare();originals=[s.saved_attempt for s in self.saved_slots];seen=[];error=KeyboardInterrupt()
        actual=slots._ProfileSectionExchange.retire
        def fail(inner):
            seen.append(inner)
            if inner is originals[0]:raise error
            return actual(inner)
        self.aliases()
        with patch.object(slots._ProfileSectionExchange,'retire',fail):
            with self.assertRaises(KeyboardInterrupt)as caught:self.wrapper()
        self.assertIs(caught.exception,error);self.assertEqual(seen,originals)
        self.assertIs(self.saved_slots[0].cleanup_error,error)
        self.assertEqual([s.cleanup for s in self.saved_slots[1:]],['close-returned']*2)
        self.assertIs(self.active[self.original],self.duty);self.assertEqual(self.hooks,[])

    def test_DC07_positive_prepare_keeps_old_alias_refusal(self):
        self.aliases()
        with self.assertRaises(slots._RequestUnavailable):slots._prepare_profile_section_slot_data(self.duty,0)
        self.assertEqual(self.saved_slots[0].construction,'unattempted')
        self.assertIsNone(self.wrapper());self.assertEqual(self.hooks,[])

    def test_DC08_positive_run_keeps_old_plan_identity_refusal(self):
        self.prepare();self.aliases()
        with self.assertRaises(slots._RequestUnavailable):slots._run_profile_section_slot_data(self.duty,0,object(),object(),object())
        self.assertEqual(self.saved_slots[0].execution,'unattempted')
        self.assertIsNone(self.wrapper());self.assertEqual(self.hooks,[])

    def test_DC09_current_owner_registry_replacement_still_refuses_before_effect(self):
        self.aliases();self.owner._guest_profile_attempts={}
        with self.assertRaises(retirement._RequestUnavailable):self.wrapper()
        self.assertFalse(self.record._retired)
        self.assertEqual([s.cleanup for s in self.saved_slots],['unattempted']*3)
        self.assertIs(self.active[self.original],self.duty)

    def test_DC10_foreign_row_in_captured_active_table_is_never_deleted(self):
        foreign=object();self.active[self.original]=foreign;self.aliases()
        with self.assertRaises(retirement._RequestUnavailable):self.wrapper()
        self.assertIs(self.active[self.original],foreign);self.assertIs(self.native[self.original],self.duty)
        self.assertTrue(self.record._retired)
        self.assertEqual([s.cleanup for s in self.saved_slots],['returned-no-attempt']*3)
