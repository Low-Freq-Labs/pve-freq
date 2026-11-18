"""Local original broker release refusal; no native service/physical proof."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from freq.services.cluster_pilot_http import _OriginalHTTPRequests, _OriginalRequest
from freq.services import pilot_guest_profile_request_cleanup as cleanup
from freq.services import pilot_guest_profile_retirement as retirement
from freq.services import pilot_guest_profile_begin as begin
from freq.services import pilot_guest_profile_begin_admission as admission
from test_guest_profile_request_cleanup_data import ProfileRequestCleanupData
from test_guest_profile_begin_admission_data import ProfileBeginAdmissionData


class ProfileReleaseHoldData(unittest.TestCase):
    def setUp(self):
        self.socket = object()
        self.original = _OriginalRequest(self.socket, 12.0, '127.0.0.1')
        self.original.handler = object()
        self.original.body, self.original.frame = object(), object()
        self.original.operation, self.original.phase = 'guest-owner-profile', 'ready'
        self.broker = _OriginalHTTPRequests(object())
        self.broker._requests[self.socket] = self.original

    def fields(self):
        o = self.original
        return o.handler, o.body, o.frame, o.guest_response, o.phase

    def held(self, close_returned=True):
        before = self.fields()
        self.assertIs(self.broker._release(self.socket, close_returned), False)
        self.assertIs(self.broker._requests[self.socket], self.original)
        self.assertEqual(self.fields(), before)
        self.assertIs(self.broker._live, False)
        self.assertTrue(self.broker._gate.acquire(blocking=False))
        self.broker._gate.release()

    def test_RH01_no_profile_effect_keeps_existing_successful_release(self):
        self.assertFalse(self.original.profile_custody_started)
        self.assertTrue(self.broker._release(self.socket, True))
        self.assertNotIn(self.socket, self.broker._requests)
        self.assertEqual(self.original.phase, 'retired')
        self.assertIsNone(self.original.handler)

    def test_RH02_started_profile_retains_all_original_fields_after_socket_close(self):
        self.original.profile_custody_started = True
        self.held()
        self.held()  # Release cannot repair/reopen/refund a retained request.

    def test_RH03_unknown_socket_close_preserves_profile_cleanup_context(self):
        self.original.profile_custody_started = True
        self.held(False)

    def test_RH04_retired_inner_flags_are_not_a_parent_receipt(self):
        self.original.profile_custody_started = True
        self.original.guest_response = SimpleNamespace(phase='retired', cleanup='returned')
        self.original.phase = 'sent'
        self.held()

    def test_RH05_changed_operation_and_cleared_response_do_not_erase_hold(self):
        self.original.profile_custody_started = True
        self.original.operation = 'asset'; self.original.guest_response = None
        self.held()

    def test_RH06_retained_outer_ledger_holds_even_if_marker_was_replaced(self):
        self.original.profile_cleanup = object()
        self.held()

    def test_RH07_unknown_constructor_return_without_ledger_holds_original(self):
        self.original.profile_cleanup_capture = 'constructor-pending'
        self.held()

    def test_RH08_capture_error_is_retained_and_cannot_authorize_release(self):
        error = MemoryError(); self.original.profile_cleanup_capture_error = error
        self.held()
        self.assertIs(self.original.profile_cleanup_capture_error, error)

    def test_RH09_foreign_capture_and_marker_are_never_compared_with_hooks(self):
        seen = []
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
            def __eq__(self, other): seen.append('eq'); raise AssertionError('eq')
        self.original.profile_cleanup_capture = Trap()
        self.held()
        self.original.profile_cleanup_capture = 'unattempted'
        self.original.profile_custody_started = Trap()
        self.held(); self.assertEqual(seen, [])

    def test_RH10_known_profile_route_with_foreign_response_is_retained_without_hooks(self):
        seen = []
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
        self.original.guest_response = Trap()
        self.held(); self.assertEqual(seen, [])

    def test_RH11_actual_begin_sets_hold_before_admission_constructor_failure(self):
        f = ProfileBeginAdmissionData(); f.setUp()
        fixture, original = f.f, f.original
        template = f.begin; original.guest_response = None
        original.profile_custody_started = False
        f.store._auth._capture_session = lambda *unused: (original, template.token, 'cookie', template.session, template.values)
        error = MemoryError(); seen = []
        def fail(guard, transaction, request, duty):
            self.assertTrue(request.profile_custody_started)
            self.assertIs(request.guest_response, duty); seen.append(duty)
            raise error
        with fixture.ports(), \
             patch.object(begin, '_owned_store', return_value=fixture.owner), \
             patch.object(begin.auth, '_cluster_pilot_direct_tls', return_value=True), \
             patch.object(begin.auth, 'same_origin_or_absent', return_value=True), \
             patch.object(fixture.broker.__class__, '_body_json', return_value={'owner_ref': template.family_ref, 'guest_ref': template.guest_ref}), \
             patch.object(admission._ProfileBeginAdmissionGates, '__init__', fail):
            with self.assertRaises(MemoryError) as caught: begin.begin_profile(f.store, fixture.handler)
        self.assertIs(caught.exception, error); self.assertEqual(seen, [original.guest_response])
        self.assertTrue(original.profile_custody_started)

    def test_RH12_actual_cleanup_sets_hold_before_partial_ledger_constructor(self):
        f = ProfileRequestCleanupData(); f.setUp()
        f.original.profile_custody_started = False
        error = MemoryError()
        def fail(duty, store, original, handler):
            self.assertTrue(original.profile_custody_started)
            self.assertIs(original.profile_cleanup, duty)
            raise error
        with patch.object(cleanup._ProfileRequestCleanup, '__init__', fail):
            with self.assertRaises(MemoryError) as caught: f.call()
        self.assertIs(caught.exception, error)
        self.assertTrue(f.original.profile_custody_started)

    def test_RH13_other_route_with_no_profile_hold_keeps_prior_release(self):
        self.original.operation = 'guest-owner-open'
        self.original.guest_response = object()
        self.assertTrue(self.broker._release(self.socket, True))
        self.assertNotIn(self.socket, self.broker._requests)

    def test_RH14_busy_broker_gate_keeps_original_context_without_release_retry(self):
        self.original.profile_custody_started = True
        self.broker._gate.acquire(blocking=False)
        before = self.fields()
        try:
            self.assertFalse(self.broker._release(self.socket, True))
            self.assertEqual(self.fields(), before)
            self.assertIs(self.broker._requests[self.socket], self.original)
        finally:
            self.broker._gate.release()
        self.assertFalse(self.broker._live)
