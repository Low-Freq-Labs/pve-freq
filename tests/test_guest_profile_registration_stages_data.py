"""Fictional retained constructor/outer insertion faults; no original native grant."""
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from test_guest_profile_registration_data import ProfileRegistrationData
from freq.services import pilot_guest_profile_registration as source


class ProfileRegistrationStagesData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileRegistrationData();self.f.setUp()
        self.begin=self.f.begin;self.original=self.begin.original
        self.duty=source._retain_profile_registration_duty_data(self.begin,self.original)
        self.handler=object()

    def plan(self):return source._retain_profile_plan_data(self.f.owner,self.duty,112.5)
    def custody(self):return source._retain_profile_custody_data(self.f.store,self.original,self.handler,self.duty)
    def insert(self):return source._retain_profile_registration_call_data(self.f.owner,self.duty)
    def handoff(self):
        self.plan()
        d=self.duty
        d.credential_uid,d.configured_token=2001,('fixture@pam','fixture-token-name')
        d.component_tables=self.f.owner._original_component_tables
        d.inventory_tables=self.f.owner._original_guest_inventory_tables
        d.profile_tables=self.f.owner._original_guest_profile_tables
        self.original.guest_response=d
        self.begin.phase='registration-attempted'
    def captured(self):self.handoff();self.custody();self.duty.phase='captured'

    def test_PS01_plan_partial_is_retained_before_real_initialization(self):
        init=source._GuestProfileSubreadsData.__init__;seen=[]
        def watched(plan,owner,begin,now):
            seen.append(plan);self.assertIs(self.duty.plan,plan)
            self.assertEqual(self.duty.plan_capture,'constructor-pending')
            self.assertIs(self.original.guest_response,self.begin)
            init(plan,owner,begin,now)
        with patch.object(source._GuestProfileSubreadsData,'__init__',watched):plan=self.plan()
        self.assertEqual(seen,[plan]);self.assertEqual(len(plan.reads),3)
        self.assertEqual(self.duty.plan_capture,'constructor-returned')

    def test_PS02_plan_init_memory_retains_same_partial_and_refuses_retry(self):
        error=MemoryError();seen=[]
        def fail(plan,*unused):seen.append(plan);raise error
        with patch.object(source._GuestProfileSubreadsData,'__init__',fail):
            for unused in range(2):
                with self.assertRaises(MemoryError)as caught:self.plan()
                self.assertIs(caught.exception,error)
        self.assertEqual(seen,[self.duty.plan]);self.assertIs(self.duty.plan_error,error)
        self.assertEqual(self.duty.plan_capture,'constructor-pending')
        self.assertIs(self.original.guest_response,self.begin)

    def test_PS03_plan_new_failure_is_pending_without_holder_and_never_retried(self):
        error=KeyboardInterrupt();allocate=Mock(side_effect=error)
        with patch.object(source,'_GuestProfileSubreadsData',SimpleNamespace(__new__=allocate)):
            for unused in range(2):
                with self.assertRaises(KeyboardInterrupt)as caught:self.plan()
                self.assertIs(caught.exception,error)
        self.assertEqual(allocate.call_count,1);self.assertIsNone(self.duty.plan)
        self.assertEqual(self.duty.plan_capture,'constructor-pending')

    def test_PS04_returned_plan_cannot_be_reconstructed(self):
        plan=self.plan()
        with self.assertRaises(source._RequestUnavailable):self.plan()
        self.assertIs(self.duty.plan,plan)

    def test_PS05_custody_same31_partial_before_real_initializer(self):
        self.handoff();init=source._ProfileRetirementCustody.__init__;seen=[]
        def watched(custody,*args):
            seen.append(custody);self.assertIs(self.duty.custody,custody)
            self.assertEqual(self.duty.custody_capture,'constructor-pending')
            init(custody,*args)
        with patch.object(source._ProfileRetirementCustody,'__init__',watched):custody=self.custody()
        self.assertEqual(seen,[custody]);self.assertEqual(len(custody.items),31)
        self.assertIs(custody.items[14],self.duty);self.assertIs(custody.items[30],self.duty.plan)

    def test_PS06_custody_partial_control_is_retained_and_never_reconstructed(self):
        self.handoff();error=SystemExit();seen=[]
        def fail(custody,*unused):seen.append(custody);raise error
        with patch.object(source._ProfileRetirementCustody,'__init__',fail):
            for unused in range(2):
                with self.assertRaises(SystemExit)as caught:self.custody()
                self.assertIs(caught.exception,error)
        self.assertEqual(seen,[self.duty.custody]);self.assertIs(self.duty.custody_error,error)
        self.assertEqual(self.duty.custody_capture,'constructor-pending')
        self.assertIs(self.original.guest_response,self.duty)

    def test_PS07_custody_new_failure_keeps_pending_no_holder(self):
        self.handoff();error=MemoryError();allocate=Mock(side_effect=error)
        with patch.object(source,'_ProfileRetirementCustody',SimpleNamespace(__new__=allocate)):
            for unused in range(2):
                with self.assertRaises(MemoryError)as caught:self.custody()
                self.assertIs(caught.exception,error)
        self.assertEqual(allocate.call_count,1);self.assertIsNone(self.duty.custody)
        self.assertEqual(self.duty.custody_capture,'constructor-pending')

    def test_PS08_real_inner_insert_keeps_same_permanent_and_active_duty(self):
        self.captured();self.assertIs(self.insert(),True)
        self.assertIs(self.f.owner._native_guest_profile_attempts[self.original],self.duty)
        self.assertIs(self.f.owner._guest_profile_attempts[self.original],self.duty)
        self.assertEqual(self.duty.registration_state,'call-returned')
        with self.assertRaises(source._RequestUnavailable):self.insert()
        self.assertEqual(len(self.f.owner._native_guest_profile_attempts),1)

    def test_PS09_lost_successful_inner_return_stays_pending_despite_inner_registered(self):
        self.captured();inner=source._register_profile_duty_data;error=MemoryError();calls=[]
        def lost(owner,duty):calls.append(duty);self.assertTrue(inner(owner,duty));raise error
        with patch.object(source,'_register_profile_duty_data',lost):
            for unused in range(2):
                with self.assertRaises(MemoryError)as caught:self.insert()
                self.assertIs(caught.exception,error)
        self.assertEqual(calls,[self.duty]);self.assertEqual(self.duty.phase,'registered')
        self.assertEqual(self.duty.registration_state,'call-pending')
        self.assertIsNone(self.duty.registration_return);self.assertIs(self.duty.registration_error,error)
        self.assertIs(self.f.owner._native_guest_profile_attempts[self.original],self.duty)

    def test_PS10_false_inner_return_is_retained_once_without_insertion(self):
        self.captured()
        with patch.object(source,'_register_profile_duty_data',return_value=False)as inner:
            self.assertIs(self.insert(),False)
            with self.assertRaises(source._RequestUnavailable):self.insert()
        self.assertEqual(inner.call_count,1);self.assertEqual(self.duty.registration_state,'call-returned')
        self.assertEqual(self.f.owner._native_guest_profile_attempts,{})

    def test_PS11_foreign_inner_return_is_retained_but_never_accepted(self):
        self.captured();foreign=object()
        with patch.object(source,'_register_profile_duty_data',return_value=foreign)as inner:
            with self.assertRaises(source._CorruptProfileSource)as first:self.insert()
            with self.assertRaises(source._CorruptProfileSource)as second:self.insert()
        self.assertIs(first.exception,second.exception);self.assertIs(self.duty.registration_return,foreign)
        self.assertEqual(self.duty.registration_state,'call-pending');self.assertEqual(inner.call_count,1)

    def test_PS12_preinsert_control_keeps_same_error_without_retry_or_insert(self):
        self.captured();error=KeyboardInterrupt()
        with patch.object(source,'_register_profile_duty_data',side_effect=error)as inner:
            for unused in range(2):
                with self.assertRaises(KeyboardInterrupt)as caught:self.insert()
                self.assertIs(caught.exception,error)
        self.assertEqual(inner.call_count,1);self.assertEqual(self.f.owner._guest_profile_attempts,{})
        self.assertEqual(self.duty.registration_state,'call-pending')

    def test_PS13_foreign_holder_rejected_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign hook')
        for call in (lambda:source._retain_profile_plan_data(self.f.owner,Trap(),112.5),
                     lambda:source._retain_profile_custody_data(self.f.store,self.original,self.handler,Trap()),
                     lambda:source._retain_profile_registration_call_data(self.f.owner,Trap())):
            with self.assertRaises(source._RequestUnavailable):call()

    def test_PS14_wrong_original_or_response_refuses_before_custody_or_plan(self):
        self.original.guest_response=object()
        with self.assertRaises(source._RequestUnavailable):self.plan()
        self.assertEqual(self.duty.plan_capture,'unattempted')
        self.original.guest_response=self.duty
        with self.assertRaises(source._RequestUnavailable):source._retain_profile_custody_data(self.f.store,object(),self.handler,self.duty)
        self.assertEqual(self.duty.custody_capture,'unattempted')

    def test_PS15_partial_capture_never_refunds_guest_or_renews_original_end(self):
        r=self.begin.record
        before=(r._spent,r._retired,r._last_clock,r._ticket._remaining,self.original.end,self.original.write_end,self.begin.end)
        self.captured()
        self.assertEqual((r._spent,r._retired,r._last_clock,r._ticket._remaining,self.original.end,self.original.write_end,self.begin.end),before)
