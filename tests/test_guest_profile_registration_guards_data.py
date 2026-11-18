"""UNRUN fictional timed-guard ports; no original entry/native/physical grant."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from contextlib import contextmanager
from test_guest_profile_begin_admission_data import ProfileBeginAdmissionData
from freq.services import pilot_guest_profile_registration_guards as source


@contextmanager
def refusing_allocator(error):
    """Replace only module binding; leave canonical class constructor slots intact."""
    allocator = Mock(side_effect=error)
    with patch.object(source, '_ProfileRegistrationAdmissionGates', SimpleNamespace(__new__=allocator)):
        yield allocator


class ProfileRegistrationGuardsData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileBeginAdmissionData()
        self.f.setUp()
        self.begin,self.original,self.store=self.f.begin,self.f.original,self.f.store
        self.quarantines=[]
        self.store._quarantine=lambda error:self.quarantines.append(error)or error

    def guard(self):
        return source._retain_profile_registration_guards_data(self.store._auth,self.original,self.begin)

    def failed(self,guard,body):
        try:
            with guard:raise body
        except BaseException as error:
            return source._finish_profile_registration_guard_error(self.store,guard,error)

    def test_RG01_same_four_timed_locks_shorter_end_currentness_and_reverse_release(self):
        self.original.write_end=113.5
        with self.f.ports():
            g=self.guard()
            with g:pass
        self.assertIs(self.begin.registration_guards,g)
        self.assertEqual(self.begin.registration_guard_capture,'constructor-returned')
        self.assertTrue(all(e[2]==0.5 for e in self.f.events if e[0]=='acquire'))
        self.assertEqual([e for e in self.f.events if e[0]=='release'],[('release',i)for i in range(3,-1,-1)])
        self.assertEqual(self.quarantines,[])

    def test_RG02_constructor_memory_keeps_same_partial_guard_before_init(self):
        error=MemoryError()
        seen=[]
        def fail(guards,transaction,original,begin):
            seen.append(guards)
            self.assertIs(begin.registration_guards,guards)
            self.assertEqual(begin.registration_guard_capture,'constructor-pending')
            raise error
        with patch.object(source._ProfileRegistrationAdmissionGates,'__init__',fail):
            with self.assertRaises(MemoryError)as caught:self.guard()
        self.assertIs(caught.exception,error)
        self.assertIs(self.begin.registration_guards,seen[0])
        self.assertIs(self.begin.registration_guard_error,error)
        self.assertEqual(self.f.events,[])

    def test_RG03_unknown_acquire_never_raw_released_earlier_known_released_quarantine_once(self):
        error=KeyboardInterrupt()
        self.f.locks[2].acquire_error=error
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,ValueError()),error)
        self.assertIs(g.acquire_errors[2],error)
        self.assertEqual(g._states[2],'acquire-pending')
        self.assertEqual([e for e in self.f.events if e[0]=='release'],[('release',1),('release',0)])
        self.assertEqual(self.quarantines,[error])

    def test_RG04_known_busy_refusal_is_not_global_quarantine(self):
        self.f.locks[1].acquired=False
        with self.f.ports():
            g=self.guard()
            error=self.failed(g,ValueError())
        self.assertIsInstance(error,source._RequestUnavailable)
        self.assertEqual(g._states[1],'not-acquired')
        self.assertEqual(self.quarantines,[])
        self.assertEqual([e for e in self.f.events if e[0]=='release'],[('release',0)])

    def test_RG05_body_control_survives_all_release_errors_and_prior_begin_history_unchanged(self):
        prior=ValueError('prior begin')
        self.begin.body_error=prior
        body=SystemExit()
        failures=[MemoryError(),KeyboardInterrupt(),ValueError(),MemoryError()]
        for lock,error in zip(self.f.locks,failures):lock.release_error=error
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,body),body)
        self.assertIs(g.body_error,body)
        self.assertIs(self.begin.body_error,prior)
        self.assertEqual(g.release_errors,failures)
        self.assertEqual(len([e for e in self.f.events if e[0]=='release']),4)
        self.assertEqual(self.quarantines,[body])

    def test_RG06_release_memory_replaces_ordinary_body_keeps_both_objects(self):
        body,memory=ValueError(),MemoryError()
        self.f.locks[3].release_error=memory
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,body),memory)
        self.assertIs(g.body_error,body)
        self.assertIs(g.release_errors[3],memory)
        self.assertEqual(self.quarantines,[memory])

    def test_RG07_outer_lost_entry_return_visits_still_known_owned_locks(self):
        error=MemoryError()
        with self.f.ports():
            g=self.guard()
            # Fictional outside-return loss after inner entry acquired all.
            g.__enter__()
            self.assertIs(source._finish_profile_registration_guard_error(self.store,g,error),error)
        self.assertEqual(g._states,['released']*4)
        self.assertEqual([e for e in self.f.events if e[0]=='release'],[('release',i)for i in range(3,-1,-1)])
        self.assertEqual(self.quarantines,[])

    def test_RG08_quarantine_secondary_memory_cannot_replace_earlier_control(self):
        control,memory=KeyboardInterrupt(),MemoryError()
        self.f.locks[0].acquire_error=control
        def fail(error):raise memory
        self.store._quarantine=fail
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,ValueError()),control)
        self.assertIs(g.quarantine_input,control)
        self.assertIs(g.quarantine_error,memory)
        self.assertIs(g.primary,control)

    def test_RG09_same_error_finish_repeat_never_releases_or_quarantines_twice(self):
        error=MemoryError()
        self.f.locks[2].acquire_error=error
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,ValueError()),error)
            events=tuple(self.f.events)
            self.assertIs(source._finish_profile_registration_guard_error(self.store,g,error),error)
        self.assertEqual(tuple(self.f.events),events)
        self.assertEqual(self.quarantines,[error])
        self.assertIs(g.repeat_error,error)

    def test_RG10_first_control_repeat_retained_and_further_distinct_repeat_unsupported(self):
        first,later=MemoryError(),KeyboardInterrupt()
        with self.f.ports():
            g=self.guard()
            self.assertIs(source._finish_profile_registration_guard_error(self.store,g,first),first)
            self.assertIs(source._finish_profile_registration_guard_error(self.store,g,later),later)
            with self.assertRaises(KeyboardInterrupt)as caught:
                source._finish_profile_registration_guard_error(self.store,g,SystemExit())
        self.assertIs(caught.exception,later)
        self.assertIs(g.outer_error,first)
        self.assertIs(g.repeat_error,later)
        self.assertEqual(self.quarantines,[])

    def test_RG11_currentness_failure_releases_all_without_global_quarantine(self):
        error=ValueError()
        def fail(*unused):raise error
        self.store._auth._current_locked=fail
        with self.f.ports():
            g=self.guard()
            self.assertIs(self.failed(g,MemoryError()),error)
        self.assertIs(g.currentness_error,error)
        self.assertEqual(g._states,['released']*4)
        self.assertEqual(self.quarantines,[])

    def test_RG12_foreign_guard_or_begin_refuses_before_hooks(self):
        class Trap:
            def __getattribute__(self,name):raise AssertionError('foreign hook')
        with self.assertRaises(source._RequestUnavailable):source._retain_profile_registration_guards_data(object(),self.original,Trap())
        with self.assertRaises(source._RequestUnavailable):source._finish_profile_registration_guard_error(self.store,Trap(),MemoryError())
        self.assertEqual(self.f.events,[])

    def test_RG13_pending_guard_constructor_never_retries(self):
        self.begin.registration_guard_capture='constructor-pending'
        with refusing_allocator(AssertionError('retry')):
            with self.assertRaises(source._RequestUnavailable):self.guard()
        self.assertIsNone(self.begin.registration_guards)
        self.assertEqual(self.f.events,[])
