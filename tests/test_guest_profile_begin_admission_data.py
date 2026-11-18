"""UNRUN fictional original timed-guard and retained received-error declarations."""
import unittest
from contextlib import contextmanager, ExitStack
from unittest.mock import patch
from test_guest_profile_begin_capture_data import ProfileBeginCaptureData
from freq.services import pilot_guest_profile_begin_admission as source
from freq.services import pilot_guest_profile_begin as begin_source
from freq.api import auth


class FictionalTimedGuard:
    def __init__(self, index, events):
        self.index, self.events = index, events
        self.acquire_error = self.release_error = None
        self.acquired = True
    def acquire(self, *, timeout):
        self.events.append(('acquire',self.index,timeout))
        if self.acquire_error is not None: raise self.acquire_error
        return self.acquired
    def release(self):
        self.events.append(('release',self.index))
        if self.release_error is not None: raise self.release_error


class ProfileBeginAdmissionData(unittest.TestCase):
    def setUp(self):
        self.c = ProfileBeginCaptureData()
        self.c.setUp()
        self.f=self.c.fixture
        self.begin,self.store,self.original=self.f.begin,self.f.store,self.f.original
        self.events=[]
        self.locks=[FictionalTimedGuard(i,self.events) for i in range(4)]
        self.f.owner._gate=self.locks[0]
        self.store._references._lock=self.locks[2]
        self.f.broker._gate=self.locks[3]
        transaction=self.store._auth
        transaction._installation=self.f.owner
        transaction._references=self.store._references
        transaction._broker=self.f.broker
        transaction._current_locked=lambda *unused:self.events.append(('current',))
        self.begin.admission=self.begin.admission_error=self.begin.body_error=self.begin.primary_error=None
        self.begin.admission_capture='unattempted'
        self.begin.guard_inspection_error=None
        self.begin.quarantine_inputs=[None]*6
        self.begin.quarantine_returns=[None]*6
        self.begin.quarantine_errors=[None]*6
        self.begin.quarantine_repeat_errors=[None]*6
        self.store._quarantine=lambda error:error

    @contextmanager
    def ports(self):
        with patch.object(auth,'_auth_lock',self.locks[1]),patch.object(source.time,'monotonic',return_value=113.0):
            yield

    def guards(self):
        return source._ProfileBeginAdmissionGates(self.store._auth,self.original,self.begin)

    def test_BA01_same_four_timed_guards_currentness_then_reverse_releases(self):
        with self.ports():
            g=self.guards()
            with g: self.events.append(('body',))
        self.assertEqual([e[:2] for e in self.events if e[0]=='acquire'],[('acquire',i) for i in range(4)])
        self.assertTrue(all(e[2]==self.begin.end-113.0 for e in self.events if e[0]=='acquire'))
        self.assertEqual(self.events[4:6],[('current',),('body',)])
        self.assertEqual(self.events[-4:],[('release',i) for i in range(3,-1,-1)])
        self.assertFalse(source._begin_guard_uncertain_data(g))

    def test_BA02_unknown_acquire_is_retained_not_released_and_known_earlier_release_runs(self):
        error=KeyboardInterrupt()
        self.locks[2].acquire_error=error
        with self.ports():
            g=self.guards()
            with self.assertRaises(KeyboardInterrupt) as caught:
                with g: raise AssertionError('must not enter')
        self.assertIs(caught.exception,error)
        self.assertIs(g.acquire_errors[2],error)
        self.assertEqual(g._states[2],'acquire-pending')
        self.assertEqual([e for e in self.events if e[0]=='release'],[('release',1),('release',0)])
        self.assertTrue(source._begin_guard_uncertain_data(g))

    def test_BA03_known_busy_guard_refusal_is_not_global_unknown(self):
        self.locks[1].acquired=False
        with self.ports():
            g=self.guards()
            with self.assertRaises(source._RequestUnavailable):
                with g: raise AssertionError('must not enter')
        self.assertEqual(g._states[1],'not-acquired')
        self.assertFalse(source._begin_guard_uncertain_data(g))
        self.assertEqual([e for e in self.events if e[0]=='release'],[('release',0)])

    def test_BA04_all_release_errors_visited_and_body_control_remains_first(self):
        body=SystemExit()
        errors=[MemoryError(),KeyboardInterrupt(),ValueError(),MemoryError()]
        for lock,error in zip(self.locks,errors):lock.release_error=error
        with self.ports():
            g=self.guards()
            with self.assertRaises(SystemExit) as caught:
                with g: raise body
        self.assertIs(caught.exception,body)
        self.assertIs(g.body_error,body)
        self.assertIs(self.begin.body_error,body)
        self.assertEqual(g.release_errors,errors)
        self.assertEqual(len([e for e in self.events if e[0]=='release']),4)

    def test_BA05_release_memory_replaces_ordinary_body_but_retains_both(self):
        body=ValueError()
        memory=MemoryError()
        self.locks[3].release_error=memory
        with self.ports():
            g=self.guards()
            with self.assertRaises(MemoryError) as caught:
                with g: raise body
        self.assertIs(caught.exception,memory)
        self.assertIs(g.body_error,body)
        self.assertIs(g.release_errors[3],memory)
        self.assertEqual(len([e for e in self.events if e[0]=='release']),4)

    def test_BA06_currentness_refusal_releases_all_without_positive_body(self):
        error=source._RequestUnavailable()
        def current(*unused):raise error
        self.store._auth._current_locked=current
        with self.ports():
            g=self.guards()
            with self.assertRaises(source._RequestUnavailable) as caught:
                with g: raise AssertionError('must not enter')
        self.assertIs(caught.exception,error)
        self.assertIs(g.currentness_error,error)
        self.assertFalse(source._begin_guard_uncertain_data(g))
        self.assertEqual(len([e for e in self.events if e[0]=='release']),4)

    def test_BA07_shorter_original_write_end_is_used_for_every_wait_without_renewal(self):
        self.original.write_end=113.5
        with self.ports():
            g=self.guards()
            with g: pass
        self.assertEqual(g._end,113.5)
        self.assertTrue(all(e[2]==0.5 for e in self.events if e[0]=='acquire'))

    def test_BA08_exact_expired_end_refuses_before_any_lock_call(self):
        self.original.write_end=113.0
        with self.ports():
            g=self.guards()
            with self.assertRaises(source._RequestUnavailable):
                with g: raise AssertionError('must not enter')
        self.assertEqual(self.events,[])
        self.assertFalse(source._begin_guard_uncertain_data(g))

    def test_BA09_quarantine_input_return_error_retained_and_control_not_replaced(self):
        control=KeyboardInterrupt()
        memory=MemoryError()
        def fail(error):raise memory
        self.store._quarantine=fail
        selected=source._quarantine_begin_error(self.store,self.begin,control,0)
        self.assertIs(selected,control)
        self.assertIs(self.begin.quarantine_inputs[0],control)
        self.assertIs(self.begin.quarantine_errors[0],memory)
        self.assertIsNone(self.begin.quarantine_returns[0])

    def test_BA10_same_quarantine_site_cannot_be_called_twice_after_failed_return(self):
        memory=MemoryError()
        calls=[]
        def fail(error):calls.append(error);raise memory
        self.store._quarantine=fail
        first=source._RequestUnavailable()
        selected=source._quarantine_begin_error(self.store,self.begin,first,3)
        repeated=source._quarantine_begin_error(self.store,self.begin,first,3)
        self.assertIs(selected,memory)
        self.assertIs(repeated,memory)
        self.assertEqual(calls,[first])

    def test_BA11_foreign_quarantine_return_is_retained_but_cannot_become_primary(self):
        error=MemoryError()
        foreign=object()
        self.store._quarantine=lambda unused:foreign
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,error,2),error)
        self.assertIs(self.begin.quarantine_returns[2],foreign)
        self.assertIsInstance(self.begin.quarantine_errors[2],source._RequestUnavailable)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,error,2),error)

    def test_BA12_original_begin_prepublishes_duty_before_admission_constructor_failure(self):
        f=self.f
        template=self.begin
        error=MemoryError()
        f.original.guest_response=None
        self.store._auth._capture_session=lambda *unused:(f.original,template.token,'cookie',template.session,template.values)
        def fail(guard,transaction,original,duty):
            self.assertIs(original.guest_response,duty)
            self.assertIs(duty.admission,guard)
            self.assertEqual(duty.admission_capture,'constructor-pending')
            raise error
        with f.ports(), ExitStack() as p:
            p.enter_context(patch.object(begin_source,'_owned_store',return_value=f.owner))
            p.enter_context(patch.object(begin_source.auth,'_cluster_pilot_direct_tls',return_value=True))
            p.enter_context(patch.object(begin_source.auth,'same_origin_or_absent',return_value=True))
            p.enter_context(patch.object(f.broker.__class__,'_body_json',return_value={'owner_ref':template.family_ref,'guest_ref':template.guest_ref}))
            p.enter_context(patch.object(source._ProfileBeginAdmissionGates,'__init__',fail))
            with self.assertRaises(MemoryError) as caught:begin_source.begin_profile(self.store,f.handler)
        duty=f.original.guest_response
        self.assertIs(caught.exception,error)
        self.assertIs(duty.admission_error,error)
        self.assertIs(duty.primary_error,error)
        self.assertIsNotNone(duty.admission)
        self.assertEqual(self.events,[])

    def test_BA13_distinct_controls_keep_first_and_retain_later_without_second_call(self):
        first,later=KeyboardInterrupt(),SystemExit()
        calls=[]
        self.store._quarantine=lambda error:(calls.append(error) or error)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,first,0),first)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,later,0),first)
        self.assertIs(self.begin.quarantine_repeat_errors[0],later)
        self.assertIs(self.begin.primary_error,first)
        self.assertEqual(calls,[first])

    def test_BA14_distinct_memory_errors_keep_first_and_retain_later(self):
        first,later=MemoryError(),MemoryError()
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,first,1),first)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,later,1),first)
        self.assertIs(self.begin.quarantine_repeat_errors[1],later)
        self.assertIs(self.begin.primary_error,first)

    def test_BA15_other_site_earlier_control_remains_primary_during_ordinary_repeat(self):
        ordinary,later,control=ValueError(),RuntimeError(),KeyboardInterrupt()
        source._quarantine_begin_error(self.store,self.begin,ordinary,2)
        source._quarantine_begin_error(self.store,self.begin,control,3)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,later,2),control)
        self.assertIs(self.begin.quarantine_repeat_errors[2],later)
        self.assertIs(self.begin.primary_error,control)

    def test_BA16_first_repeat_control_outranks_prior_memory_and_is_retained(self):
        memory,control=MemoryError(),SystemExit()
        source._quarantine_begin_error(self.store,self.begin,memory,4)
        self.assertIs(source._quarantine_begin_error(self.store,self.begin,control,4),control)
        self.assertIs(self.begin.quarantine_repeat_errors[4],control)
        self.assertIs(self.begin.quarantine_inputs[4],memory)

    def test_BA17_further_distinct_repeat_is_unsupported_no_extra_call_or_history_claim(self):
        first,later,unsupported=KeyboardInterrupt(),MemoryError(),SystemExit()
        calls=[]
        self.store._quarantine=lambda error:(calls.append(error) or error)
        source._quarantine_begin_error(self.store,self.begin,first,5)
        source._quarantine_begin_error(self.store,self.begin,later,5)
        with self.assertRaises(KeyboardInterrupt) as caught:
            source._quarantine_begin_error(self.store,self.begin,unsupported,5)
        self.assertIs(caught.exception,first)
        self.assertIs(self.begin.quarantine_repeat_errors[5],later)
        self.assertIs(self.begin.primary_error,first)
        self.assertEqual(calls,[first])
        # Unsupported third argument is not a claimed received-error history.
