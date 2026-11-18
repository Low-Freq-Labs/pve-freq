"""Local fictional four-site quarantine failure accounting; no native authority."""
import unittest
from types import SimpleNamespace
from test_guest_profile_registration_data import ProfileRegistrationData
from freq.services import pilot_guest_profile_registration as source

class ProfileRegistrationQuarantineData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileRegistrationData();self.f.setUp();self.begin=self.f.begin
        self.duty=source._retain_profile_registration_duty_data(self.begin,self.begin.original)
        self.calls=[]
        self.store=SimpleNamespace(_quarantine=lambda error:self.calls.append(error)or error)
    def call(self,error,index=0):return source._quarantine_profile_registration_error(self.store,self.duty,error,index)

    def test_QR01_each_fixed_site_retains_input_and_primary_before_call(self):
        seen=[]
        def watched(error):
            index=len(seen);self.assertIs(self.duty.quarantine_inputs[index],error)
            self.assertIs(self.duty.quarantine_primary,errors[0]);seen.append(error);return error
        errors=[ValueError()for unused in range(4)];self.store._quarantine=watched
        for index,error in enumerate(errors):self.assertIs(self.call(error,index),errors[0])
        self.assertEqual(seen,errors);self.assertEqual(self.duty.quarantine_returns,errors)
        self.assertEqual(self.duty.quarantine_errors,[None]*4)

    def test_QR02_input_control_survives_secondary_raised_memory_same_refs(self):
        control,memory=KeyboardInterrupt(),MemoryError()
        def fail(error):self.calls.append(error);raise memory
        self.store._quarantine=fail
        self.assertIs(self.call(control),control)
        self.assertIs(self.duty.quarantine_inputs[0],control)
        self.assertIs(self.duty.quarantine_errors[0],memory)
        self.assertIsNone(self.duty.quarantine_returns[0])

    def test_QR03_secondary_control_outranks_input_memory_without_erasing_it(self):
        memory,control=MemoryError(),SystemExit()
        def fail(error):raise control
        self.store._quarantine=fail
        self.assertIs(self.call(memory),control)
        self.assertIs(self.duty.quarantine_inputs[0],memory)
        self.assertIs(self.duty.quarantine_errors[0],control)

    def test_QR04_returned_memory_outranks_ordinary_and_retains_both(self):
        ordinary,memory=ValueError(),MemoryError();self.store._quarantine=lambda error:memory
        self.assertIs(self.call(ordinary),memory)
        self.assertIs(self.duty.quarantine_inputs[0],ordinary)
        self.assertIs(self.duty.quarantine_returns[0],memory)

    def test_QR05_foreign_return_retained_with_private_error_and_no_coercion(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign return hook')
            def __str__(self):raise AssertionError('coercion')
        foreign=Trap();ordinary=ValueError();self.store._quarantine=lambda error:foreign
        self.assertIs(self.call(ordinary),ordinary)
        self.assertIs(self.duty.quarantine_returns[0],foreign)
        self.assertIsInstance(self.duty.quarantine_errors[0],source._RequestUnavailable)

    def test_QR06_same_error_repeat_never_invokes_quarantine_twice(self):
        error=MemoryError();self.assertIs(self.call(error),error)
        self.assertIs(self.call(error),error);self.assertEqual(self.calls,[error])
        self.assertIs(self.duty.quarantine_repeat_errors[0],error)

    def test_QR07_first_control_repeat_replaces_prior_memory_without_new_call(self):
        memory,control=MemoryError(),KeyboardInterrupt();self.call(memory)
        self.assertIs(self.call(control),control);self.assertEqual(self.calls,[memory])
        self.assertIs(self.duty.quarantine_inputs[0],memory)
        self.assertIs(self.duty.quarantine_repeat_errors[0],control)

    def test_QR08_further_distinct_repeat_unsupported_raises_retained_primary(self):
        ordinary,memory,control=ValueError(),MemoryError(),KeyboardInterrupt()
        self.call(ordinary);self.call(memory)
        with self.assertRaises(MemoryError)as caught:self.call(control)
        self.assertIs(caught.exception,memory);self.assertEqual(self.calls,[ordinary])
        self.assertIs(self.duty.quarantine_repeat_errors[0],memory)
        self.assertIs(self.duty.quarantine_primary,memory)

    def test_QR09_first_control_stays_first_across_distinct_sites_and_controls(self):
        ordinary,memory,first,later=ValueError(),MemoryError(),SystemExit(),KeyboardInterrupt()
        for index,error in enumerate((ordinary,memory,first,later)):self.call(error,index)
        self.assertIs(self.duty.quarantine_primary,first)
        self.assertEqual(self.duty.quarantine_inputs,[ordinary,memory,first,later])
        self.assertEqual(self.calls,[ordinary,memory,first,later])

    def test_QR10_pending_input_without_return_never_repeats_unknown_call(self):
        error=MemoryError();self.duty.quarantine_inputs[1]=error;self.duty.quarantine_primary=error
        self.assertIs(self.call(error,1),error);self.assertEqual(self.calls,[])
        self.assertIsNone(self.duty.quarantine_returns[1])

    def test_QR11_foreign_duty_bool_index_and_nonexception_refuse_before_calls(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign hook')
        for call in(lambda:source._quarantine_profile_registration_error(self.store,Trap(),MemoryError(),0),
                    lambda:self.call(MemoryError(),True),lambda:self.call(MemoryError(),4),lambda:self.call(Trap())):
            with self.assertRaises(source._RequestUnavailable):call()
        self.assertEqual(self.calls,[])

    def test_QR12_registration_history_never_overwrites_prior_begin_or_stage_error(self):
        prior,stage,body=KeyboardInterrupt(),MemoryError(),ValueError()
        self.begin.primary_error=prior;self.duty.plan_error=stage
        self.call(body,3)
        self.assertIs(self.begin.primary_error,prior);self.assertIs(self.duty.plan_error,stage)
        self.assertIs(self.duty.quarantine_primary,body)
