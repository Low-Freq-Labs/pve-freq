"""UNRUN synthetic exact-type holder/four flag targets; no original authority.

Manual __new__/private seeds are explicit fictional DATA ports. Neither this
fixture nor successful setters establish original installation or native duty.
"""
import unittest
from freq.services import pilot_guest_reference_store as source


class FictionalFlagTarget:
    def __init__(self,index,events,error=None):
        object.__setattr__(self,'index',index)
        object.__setattr__(self,'events',events)
        object.__setattr__(self,'error',error)
    def __setattr__(self,name,value):
        self.events.append((self.index,name,value))
        if self.error is not None:raise self.error
        object.__setattr__(self,name,value)


class GuestStoreQuarantineData(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.targets=[FictionalFlagTarget(i,self.events)for i in range(4)]
        # Exact class is only a refusal filter, never evidence of original ctor.
        self.store=source.OriginalGuestReferenceStore.__new__(source.OriginalGuestReferenceStore)
        self.store._quarantine_first_input=self.store._quarantine_last_input=None
        self.store._quarantine_first_result=self.store._quarantine_last_result=None
        self.store._quarantine_states=['unused']*4
        self.store._quarantine_errors=[None]*4
        self.store._quarantine_targets=tuple((target,field,value)for target,field,value in zip(
            self.targets,('_uncertain','_admission_uncertain','_live','_live'),(True,True,False,False)))

    def test_GQ01_four_known_writes_in_original_order_and_input_identity(self):
        error=ValueError()
        selected=self.store._quarantine(error)
        self.assertIs(selected,error)
        self.assertEqual(self.events,[(0,'_uncertain',True),(1,'_admission_uncertain',True),(2,'_live',False),(3,'_live',False)])
        self.assertEqual(self.store._quarantine_states,['write-returned']*4)
        self.assertEqual(self.store._quarantine_errors,[None]*4)
        self.assertIs(self.store._quarantine_first_input,error)
        self.assertIs(self.store._quarantine_first_result,error)

    def test_GQ02_first_capacity_memory_does_not_skip_three_later_disable_writes(self):
        body=ValueError()
        memory=MemoryError()
        object.__setattr__(self.targets[0],'error',memory)
        selected=self.store._quarantine(body)
        self.assertIs(selected,memory)
        self.assertIs(self.store._quarantine_errors[0],memory)
        self.assertEqual(self.store._quarantine_states,['uncertain']+['write-returned']*3)
        self.assertEqual([e[0]for e in self.events],[0,1,2,3])

    def test_GQ03_all_four_caught_failures_retained_first_control_over_memory(self):
        errors=[MemoryError(),KeyboardInterrupt(),SystemExit(),ValueError()]
        for target,error in zip(self.targets,errors):object.__setattr__(target,'error',error)
        body=ValueError()
        self.assertIs(self.store._quarantine(body),errors[1])
        self.assertEqual(self.store._quarantine_errors,errors)
        self.assertEqual(self.store._quarantine_states,['uncertain']*4)
        self.assertEqual(len(self.events),4)

    def test_GQ04_caller_control_precedes_all_later_cleanup_controls_and_memory(self):
        body=SystemExit()
        for target in self.targets:object.__setattr__(target,'error',KeyboardInterrupt())
        self.assertIs(self.store._quarantine(body),body)
        self.assertEqual(len(self.events),4)
        self.assertTrue(all(isinstance(e,KeyboardInterrupt)for e in self.store._quarantine_errors))

    def test_GQ05_distinct_memory_errors_keep_this_invocation_original_memory(self):
        body=MemoryError()
        for target in self.targets:object.__setattr__(target,'error',MemoryError())
        self.assertIs(self.store._quarantine(body),body)
        self.assertTrue(all(e is not body for e in self.store._quarantine_errors))

    def test_GQ06_repeated_quarantine_never_retries_uncertain_or_returned_write(self):
        failed=MemoryError()
        object.__setattr__(self.targets[1],'error',failed)
        first=ValueError()
        self.assertIs(self.store._quarantine(first),failed)
        states=tuple(self.store._quarantine_states)
        errors=tuple(self.store._quarantine_errors)
        later=KeyboardInterrupt()
        self.assertIs(self.store._quarantine(later),later)
        self.assertEqual(len(self.events),4)
        self.assertEqual(tuple(self.store._quarantine_states),states)
        self.assertEqual(tuple(self.store._quarantine_errors),errors)
        self.assertIs(self.store._quarantine_first_input,first)
        self.assertIs(self.store._quarantine_last_input,later)
        self.assertIs(self.store._quarantine_last_result,later)

    def test_GQ07_unknown_pending_write_is_not_repeated_from_current_flag_value(self):
        self.store._quarantine_states[0]='write-pending'  # Fictional lost return, not observed closure.
        object.__setattr__(self.targets[0],'_uncertain',True)
        body=ValueError()
        self.assertIs(self.store._quarantine(body),body)
        self.assertEqual(self.store._quarantine_states[0],'write-pending')
        self.assertEqual([e[0]for e in self.events],[1,2,3])

    def test_GQ08_replaced_current_aliases_do_not_redirect_captured_cleanup_targets(self):
        replacement=FictionalFlagTarget(9,self.events)
        self.store._installation=replacement
        self.store._broker=replacement
        body=ValueError()
        self.assertIs(self.store._quarantine(body),body)
        self.assertEqual([e[0]for e in self.events],[0,1,2,3])

    def test_GQ09_foreign_holder_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign holder')
        with self.assertRaises(source._RequestUnavailable):
            source.OriginalGuestReferenceStore._quarantine(Trap(),MemoryError())

    def test_GQ10_invalid_incoming_error_refuses_with_private_fixed_error_without_str_calls(self):
        class Trap:
            def __str__(self):raise AssertionError('must not stringify')
        selected=self.store._quarantine(Trap())
        self.assertIsInstance(selected,source._RequestUnavailable)
        self.assertEqual(len(self.events),4)
