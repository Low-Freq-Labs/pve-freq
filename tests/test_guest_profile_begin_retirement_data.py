"""UNRUN fictional guard/record retirement faults; no original native grant."""
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from test_guest_profile_begin_capture_data import ProfileBeginCaptureData
from freq.services import pilot_guest_profile_begin_retirement as source
from freq.services import pilot_guest_profile_begin_capture as capture
from freq.api import auth


class FictionalGuard:
    def __init__(self, index, events, acquire_error=None, release_error=None, acquired=True):
        self.index, self.events = index, events
        self.acquire_error, self.release_error, self.acquired = acquire_error, release_error, acquired
    def acquire(self, *, blocking):
        if blocking is not False: raise AssertionError('must be nonblocking')
        self.events.append(('acquire', self.index))
        if self.acquire_error is not None: raise self.acquire_error
        return self.acquired
    def release(self):
        self.events.append(('release', self.index))
        if self.release_error is not None: raise self.release_error


class ProfileBeginRetirementData(unittest.TestCase):
    def setUp(self):
        self.capture_fixture = ProfileBeginCaptureData()
        self.capture_fixture.setUp()
        self.f = self.capture_fixture.fixture
        self.begin, self.store, self.record = self.f.begin, self.f.store, self.f.record
        self.begin.cleanup_retirement = self.begin.cleanup_retirement_capture_error = None
        self.begin.cleanup_retirement_capture = 'unattempted'
        self.events = []
        self.locks = [FictionalGuard(i, self.events) for i in range(4)]
        self.f.owner._gate = self.locks[0]
        self.store._references._lock = self.locks[2]
        self.f.broker._gate = self.locks[3]
        self.store._quarantine = lambda error: error  # Explicit fictional owner port.

    @contextmanager
    def ports(self):
        with self.f.ports(), patch.object(auth, '_auth_lock', self.locks[1]), patch.object(
                source, '_profile_retirement_original', return_value=self.f.original):
            yield

    def prepare(self, selected=True):
        capture._capture_begin_custody_data(self.store, self.f.handler, self.begin)
        if selected: capture._capture_begin_selection_data(self.store, self.f.handler, self.begin)

    def retire(self):
        return source.retire_profile_begin_handler_duty(self.store, self.f.handler)

    def test_BR01_same_record_once_and_four_guards_reverse_release_no_refund(self):
        with self.ports():
            self.prepare()
            self.record._spent = True
            remaining = self.record._ticket._remaining
            saved_rows = tuple(self.f.owner._guest_reference_records.items())
            duty = self.retire()
        self.assertTrue(self.record._retired)
        self.assertTrue(self.record._spent)
        self.assertIs(duty.record, self.record)
        self.assertEqual(duty.record_retirement, 'call-returned')
        self.assertEqual(duty.phase, 'returned')
        self.assertEqual(self.record._ticket._remaining, remaining)
        self.assertEqual(tuple(self.f.owner._guest_reference_records.items()), saved_rows)
        self.assertEqual(self.events, [('acquire',i) for i in range(4)]+[('release',i) for i in range(3,-1,-1)])

    def test_BR02_expired_positive_aliases_and_absent_selected_row_do_not_bar_saved_retirement(self):
        with self.ports():
            self.prepare()
            self.begin.end = self.f.original.end = self.f.original.write_end = 0.0
            self.begin.record, self.begin.family, self.begin.session, self.begin.values = object(), object(), {}, ()
            self.f.owner._guest_capacity._uncertain = True
            self.f.owner._guest_reference_records.clear()
            self.retire()
        self.assertTrue(self.record._retired)

    def test_BR03_replaced_original_map_refuses_without_retiring_any_record(self):
        with self.ports():
            self.prepare()
            self.f.owner._guest_reference_records = {}
            with self.assertRaises(source._RequestUnavailable): self.retire()
        self.assertFalse(self.record._retired)
        self.assertEqual(len(self.events),8)
        self.assertEqual(self.begin.cleanup_retirement.phase,'uncertain')

    def test_BR04_unknown_acquire_releases_only_prior_known_guards(self):
        error = KeyboardInterrupt()
        self.locks[2].acquire_error = error
        with self.ports():
            self.prepare()
            with self.assertRaises(KeyboardInterrupt) as caught: self.retire()
        self.assertIs(caught.exception,error)
        d=self.begin.cleanup_retirement
        self.assertIs(d.guards.acquire_errors[2],error)
        self.assertEqual(d.guards._states[2],'acquire-pending')
        self.assertEqual(self.events,[('acquire',0),('acquire',1),('acquire',2),('release',1),('release',0)])
        self.assertFalse(self.record._retired)

    def test_BR05_late_release_memory_does_not_revive_retired_record_or_retry(self):
        error = MemoryError()
        self.locks[3].release_error = error
        with self.ports():
            self.prepare()
            with self.assertRaises(MemoryError) as caught: self.retire()
            before=tuple(self.events)
            with self.assertRaises(MemoryError) as repeated: self.retire()
        self.assertIs(caught.exception,error)
        self.assertIs(repeated.exception,error)
        self.assertTrue(self.record._retired)
        self.assertEqual(self.begin.cleanup_retirement.record_retirement,'call-returned')
        self.assertEqual(tuple(self.events),before)
        self.assertEqual([v for v in self.events if v[0]=='release'],[('release',i) for i in range(3,-1,-1)])

    def test_BR06_all_release_faults_retained_first_control_over_memory_over_ordinary(self):
        errors=[ValueError(),SystemExit(),KeyboardInterrupt(),MemoryError()]
        for lock,error in zip(self.locks,errors): lock.release_error=error
        with self.ports():
            self.prepare()
            with self.assertRaises(KeyboardInterrupt) as caught: self.retire()
        self.assertIs(caught.exception,errors[2])  # Reverse visit sees control2 before control1.
        d=self.begin.cleanup_retirement
        self.assertEqual(d.guards.release_errors,errors)
        self.assertTrue(self.record._retired)
        self.assertEqual(len(self.events),8)

    def test_BR07_unknown_retire_return_keeps_pending_and_prevents_second_call(self):
        error=MemoryError()
        calls=[]
        def fail(record):
            calls.append(record)
            record._retired=True  # Simulated side effect before a lost return.
            raise error
        with self.ports():
            self.prepare()
            with patch.object(source._GuestReferenceRecord,'_retire',fail):
                with self.assertRaises(MemoryError): self.retire()
                with self.assertRaises(MemoryError): self.retire()
        self.assertEqual(calls,[self.record])
        d=self.begin.cleanup_retirement
        self.assertEqual(d.record_retirement,'call-pending')
        self.assertIs(d.record_error,error)
        self.assertTrue(self.record._retired)
        self.assertEqual(len(self.events),8)

    def test_BR08_unattempted_selection_before_consume_does_not_retire_existing_row(self):
        with self.ports():
            self.prepare(selected=False)
            d=self.retire()
        self.assertEqual(d.selection_outcome,'not-selected-before-consume')
        self.assertEqual(d.record_retirement,'unattempted')
        self.assertFalse(self.record._retired)
        self.assertEqual(len(self.events),8)

    def test_BR09_pending_selection_error_identity_retained_after_guarded_refusal(self):
        error=KeyboardInterrupt()
        with self.ports():
            self.prepare(selected=False)
            self.begin.cleanup_selection_capture='constructor-pending'
            self.begin.cleanup_selection_error=error
            with self.assertRaises(KeyboardInterrupt) as caught: self.retire()
        self.assertIs(caught.exception,error)
        self.assertFalse(self.record._retired)
        self.assertEqual(len(self.events),8)

    def test_BR10_guard_holder_allocation_failure_retains_partial_without_acquire(self):
        error=MemoryError()
        with self.ports():
            self.prepare()
            with patch.object(source._ProfileBeginRetirementGates,'__init__',side_effect=error):
                with self.assertRaises(MemoryError) as caught: self.retire()
        self.assertIs(caught.exception,error)
        d=self.begin.cleanup_retirement
        self.assertIsNotNone(d.guards)
        self.assertIs(d.guard_capture_error,error)
        self.assertEqual(d.guard_capture,'constructor-pending')
        self.assertEqual(self.events,[])
        self.assertFalse(self.record._retired)

    def test_BR11_quarantine_exception_cannot_replace_control_or_erase_secondary(self):
        control=KeyboardInterrupt()
        memory=MemoryError()
        self.locks[3].release_error=control
        def quarantine(error): raise memory
        self.store._quarantine=quarantine
        with self.ports():
            self.prepare()
            with self.assertRaises(KeyboardInterrupt) as caught: self.retire()
        self.assertIs(caught.exception,control)
        self.assertIs(self.begin.cleanup_retirement.quarantine_error,memory)
        self.assertEqual(len(self.events),8)

    def test_BR12_foreign_current_response_refuses_before_guard_or_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign duty')
        with self.ports():
            self.prepare()
            self.f.original.guest_response=Trap()
            with self.assertRaises(source._RequestUnavailable): self.retire()
        self.assertEqual(self.events,[])
        self.assertFalse(self.record._retired)

    def test_BR13_changed_selected_target_refuses_under_all_four_saved_guards(self):
        with self.ports():
            self.prepare()
            self.record._target=tuple(list(self.record._target))
            with self.assertRaises(source._RequestUnavailable): self.retire()
        self.assertFalse(self.record._retired)
        self.assertEqual(len(self.events),8)

    def test_BR14_retirement_constructor_failure_retains_same_partial_and_error(self):
        error=MemoryError()
        with self.ports():
            self.prepare()
            with patch.object(source._ProfileBeginRetirementDuty,'__init__',side_effect=error):
                with self.assertRaises(MemoryError) as caught: self.retire()
            same=self.begin.cleanup_retirement
            with self.assertRaises(MemoryError) as repeated: self.retire()
        self.assertIs(caught.exception,error)
        self.assertIs(repeated.exception,error)
        self.assertIs(self.begin.cleanup_retirement,same)
        self.assertIs(self.begin.cleanup_retirement_capture_error,error)
        self.assertEqual(self.begin.cleanup_retirement_capture,'constructor-pending')
        self.assertEqual(self.events,[])
