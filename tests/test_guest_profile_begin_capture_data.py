"""UNRUN fictional original ports and pure snapshot-before-consume declarations.

Owner/broker/auth/guard/CSRF are patched fictional ports; original admission,
real guards, credentials and native effects are never established by this DATA.
"""
import unittest
import threading
from contextlib import ExitStack
from unittest.mock import patch
from test_guest_profile_begin_custody_data import ProfileBeginCustodyData
from freq.services import pilot_guest_profile_begin_capture as source
from freq.services import pilot_guest_profile_begin as begin_source
from freq.services import pilot_guest_profile_begin_admission as admission_source


class ProfileBeginCaptureData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileBeginCustodyData()
        self.fixture.setUp()
        self.begin, self.store = self.fixture.begin, self.fixture.store
        # Match the original capture predicate using this local test thread.
        self.fixture.original.thread = threading.current_thread()
        self.begin.phase = 'new'
        self.begin.cleanup_custody = self.begin.cleanup_selection = None
        self.begin.cleanup_capture = self.begin.cleanup_selection_capture = 'unattempted'
        self.begin.cleanup_capture_error = self.begin.cleanup_selection_error = None

    def capture(self):
        return source._capture_begin_custody_data(self.store, self.fixture.handler, self.begin)

    def selected(self):
        return source._capture_begin_selection_data(self.store, self.fixture.handler, self.begin)

    def test_BC01_same21holder_retained_before_any_selection_or_consume(self):
        with self.fixture.ports():
            same = self.capture()
        self.assertIs(same, self.begin.cleanup_custody)
        self.assertEqual(len(same.items), 21)
        self.assertEqual(self.begin.cleanup_capture, 'constructor-returned')
        self.assertEqual(self.begin.cleanup_selection_capture, 'unattempted')
        self.assertFalse(self.fixture.record._spent)

    def test_BC02_same16selection_after_known21capture_never_consumes_itself(self):
        with self.fixture.ports():
            self.capture()
            same = self.selected()
        self.assertIs(same, self.begin.cleanup_selection)
        self.assertEqual(len(same.items), 16)
        self.assertIs(same.items[1], self.fixture.record)
        self.assertEqual(self.begin.cleanup_selection_capture, 'constructor-returned')
        self.assertFalse(self.fixture.record._spent)

    def test_BC03_duplicate_capture_cannot_replace_original_snapshot(self):
        with self.fixture.ports():
            saved = self.capture()
            with self.assertRaises(source._RequestUnavailable): self.capture()
        self.assertIs(self.begin.cleanup_custody, saved)

    def test_BC04_custody_constructor_memory_keeps_prepublished_partial_and_identity(self):
        error = MemoryError()
        with self.fixture.ports(), patch.object(source._ProfileBeginCustody, '__init__', side_effect=error):
            with self.assertRaises(MemoryError) as caught: self.capture()
        self.assertIs(caught.exception, error)
        self.assertIsNotNone(self.begin.cleanup_custody)
        self.assertIs(self.begin.cleanup_capture_error, error)
        self.assertEqual(self.begin.cleanup_capture, 'constructor-pending')
        self.assertFalse(self.fixture.record._spent)
        with self.assertRaises(source._RequestUnavailable): self.selected()

    def test_BC05_selection_control_keeps_prepublished_partial_without_retry(self):
        error = KeyboardInterrupt()
        with self.fixture.ports():
            self.capture()
            with patch.object(source._ProfileBeginSelection, '__init__', side_effect=error):
                with self.assertRaises(KeyboardInterrupt) as caught: self.selected()
            saved = self.begin.cleanup_selection
            with self.assertRaises(source._RequestUnavailable): self.selected()
        self.assertIs(caught.exception, error)
        self.assertIsNotNone(saved)
        self.assertIs(self.begin.cleanup_selection, saved)
        self.assertIs(self.begin.cleanup_selection_error, error)
        self.assertEqual(self.begin.cleanup_selection_capture, 'constructor-pending')
        self.assertFalse(self.fixture.record._spent)

    def test_BC06_selection_without_known_capture_refuses_before_constructor(self):
        with self.assertRaises(source._RequestUnavailable): self.selected()
        self.assertIsNone(self.begin.cleanup_selection)
        self.assertFalse(self.fixture.record._spent)

    def test_BC07_changed_initial_token_rejects_selection_and_preserves_failed_holder(self):
        with self.fixture.ports():
            self.capture()
            saved = self.begin.cleanup_custody
            self.begin.token = object()
            with self.assertRaises(source._RequestUnavailable): self.selected()
        self.assertIs(self.begin.cleanup_custody, saved)
        self.assertIsNotNone(self.begin.cleanup_selection)
        self.assertIsNotNone(self.begin.cleanup_selection_error)
        self.assertFalse(self.fixture.record._spent)

    def test_BC08_foreign_begin_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign begin')
        with self.assertRaises(source._RequestUnavailable):
            source._capture_begin_custody_data(self.store, self.fixture.handler, Trap())

    def test_BC09_replaced_original_response_prevents_snapshot_construction(self):
        self.begin.original.guest_response = object()
        with self.assertRaises(source._RequestUnavailable): self.capture()
        self.assertIsNone(self.begin.cleanup_custody)

    def run_fictional_original_begin(self, capture_failure=None):
        f = self.fixture
        original, owner, record = f.original, f.owner, f.record
        template = self.begin
        original.guest_response = None
        events = []
        class FictionalGates:
            def __init__(self, transaction, original, duty):
                self._states = ['unused'] * 4
                self.begin = duty
            def __enter__(self): events.append('enter'); return self
            def __exit__(self, kind, error, traceback):
                self.begin.body_error = error
                events.append('exit')
        self.store._guard_locked = lambda *unused: (template.cohort, template.generation, 113.0)
        self.store._csrf_nonce_locked = lambda *unused: None
        self.store._quarantine = lambda error: error
        self.store._auth._capture_session = lambda *unused: (original, template.token, 'cookie', template.session, template.values)
        saved_consume = begin_source._consume_profile_guest_data
        def consume(same, now):
            duty = original.guest_response
            self.assertIs(same, record)
            self.assertEqual((duty.cleanup_capture, duty.cleanup_selection_capture),
                             ('constructor-returned', 'constructor-returned'))
            self.assertIs(duty.cleanup_selection.items[1], record)
            events.append('consume-after-both-snapshots')
            return saved_consume(same, now)
        with f.ports(), ExitStack() as patches:
            patches.enter_context(patch.object(begin_source, '_owned_store', return_value=owner))
            patches.enter_context(patch.object(begin_source.auth, '_cluster_pilot_direct_tls', return_value=True))
            patches.enter_context(patch.object(begin_source.auth, 'same_origin_or_absent', return_value=True))
            patches.enter_context(patch.object(admission_source, '_ProfileBeginAdmissionGates', FictionalGates))
            patches.enter_context(patch.object(begin_source, '_consume_profile_guest_data', consume))
            patches.enter_context(patch.object(source._ProfileBeginCustody, '__init__', side_effect=capture_failure) if capture_failure is not None else patch.object(begin_source, '_profile_guest_data_locked', return_value=record))
            patches.enter_context(patch.object(begin_source, '_source_family_data_locked', return_value=template.family))
            patches.enter_context(patch.object(f.broker.__class__, '_body_json', return_value={'owner_ref':template.family_ref,'guest_ref':template.guest_ref}))
            result = begin_source.begin_profile(self.store, f.handler)
        return result, events

    def test_BC10_original_begin_reaches_consume_only_after_both_snapshots(self):
        result, events = self.run_fictional_original_begin()
        self.assertIs(result, self.fixture.original.guest_response)
        self.assertEqual(result.phase, 'spent')
        self.assertEqual(events, ['enter', 'consume-after-both-snapshots', 'exit'])
        self.assertTrue(self.fixture.record._spent)

    def test_BC11_original_capture_allocation_prevents_consume_and_retains_error(self):
        error = MemoryError()
        with self.assertRaises(MemoryError) as caught:
            self.run_fictional_original_begin(capture_failure=error)
        self.assertIs(caught.exception, error)
        duty = self.fixture.original.guest_response
        self.assertIs(duty.cleanup_capture_error, error)
        self.assertEqual(duty.cleanup_capture, 'constructor-pending')
        self.assertFalse(self.fixture.record._spent)

    def test_BC12_capacity_allocation_is_not_replaced_by_corrupt_source(self):
        error = MemoryError()
        b = self.begin
        with patch.object(begin_source._GuestCapacity, '_check', side_effect=error):
            with self.assertRaises(MemoryError) as caught:
                begin_source._profile_guest_data_locked(self.fixture.owner, b.family, b.session,
                    b.values[0], b.guest_ref, b.cohort, b.generation, 113.0)
        self.assertIs(caught.exception, error)
        self.assertFalse(self.fixture.record._spent)
