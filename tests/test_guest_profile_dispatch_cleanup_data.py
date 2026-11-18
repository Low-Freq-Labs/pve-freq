"""Projected actual dispatch tail and real broker release on fictional data."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from freq.services import pilot_cluster_dispatch as dispatch
from freq.services.cluster_pilot_http import _OriginalRequest, _OriginalHTTPRequests


class ProfileDispatchCleanupData(unittest.TestCase):
    def setUp(self):
        self.original = _OriginalRequest(object(), 20.0, '127.0.0.1')
        self.original.operation = 'guest-owner-profile'
        self.original.guest_response = object()
        self.original.profile_custody_started = True
        self.handler = object(); self.original.handler = self.handler
        self.events, self.refusals = [], []
        self.component = SimpleNamespace(retire_profile_request_duty=self.cleanup)
        self.dispatcher = dispatch.OriginalPilotDispatch.__new__(dispatch.OriginalPilotDispatch)
        self.dispatcher._guests = self.component
        self.dispatcher._owned = lambda handler: self.original
        self.dispatcher._write_refusal = lambda handler, error: self.refusals.append(error)

    def cleanup(self, handler):
        self.assertIs(handler, self.handler); self.events.append('cleanup')

    def dispatch_once(self):
        return self.dispatcher.run(self.handler)

    def test_PD01_partial_profile_cleanup_precedes_single_unavailable_refusal(self):
        def refusal(handler, error):
            self.assertEqual(self.events, ['cleanup']); self.refusals.append(error)
        self.dispatcher._write_refusal = refusal
        self.assertIsNone(self.dispatch_once())
        self.assertEqual(len(self.refusals), 1)
        self.assertIsInstance(self.refusals[0], dispatch._RequestUnavailable)

    def test_PD02_empty_profile_request_does_not_invent_cleanup(self):
        self.original.profile_custody_started = False
        self.original.guest_response = None
        self.dispatch_once(); self.assertEqual(self.events, [])
        self.assertEqual(len(self.refusals), 1)

    def test_PD03_pending_constructor_without_response_still_attempts_fixed_cleanup(self):
        self.original.guest_response = None
        self.dispatch_once(); self.assertEqual(self.events, ['cleanup'])

    def test_PD04_known_response_without_current_marker_still_attempts_cleanup(self):
        self.original.profile_custody_started = False
        self.dispatch_once(); self.assertEqual(self.events, ['cleanup'])

    def test_PD05_cleanup_control_prevents_refusal_and_keeps_exact_error(self):
        error = KeyboardInterrupt()
        def fail(handler): self.events.append('cleanup'); raise error
        self.component.retire_profile_request_duty = fail
        with self.assertRaises(KeyboardInterrupt) as caught: self.dispatch_once()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.refusals, []); self.assertEqual(self.events, ['cleanup'])

    def test_PD06_cleanup_allocation_prevents_refusal(self):
        error = MemoryError()
        def fail(handler): raise error
        self.component.retire_profile_request_duty = fail
        with self.assertRaises(MemoryError) as caught: self.dispatch_once()
        self.assertIs(caught.exception, error); self.assertEqual(self.refusals, [])

    def test_PD07_ordinary_cleanup_error_never_creates_positive_reply(self):
        error = ValueError()
        def fail(handler): raise error
        self.component.retire_profile_request_duty = fail
        self.dispatch_once(); self.assertEqual(len(self.refusals), 1)
        self.assertIsInstance(self.refusals[0], dispatch._RequestUnavailable)

    def test_PD08_captured_component_is_used_even_if_current_alias_changes(self):
        foreign_calls = []
        foreign = SimpleNamespace(retire_profile_request_duty=lambda h: foreign_calls.append(h))
        actual = dispatch._RequestUnavailable
        def changed():
            self.dispatcher._guests = foreign
            return actual()
        with patch.object(dispatch, '_RequestUnavailable', changed): self.dispatch_once()
        self.assertEqual(self.events, ['cleanup']); self.assertEqual(foreign_calls, [])

    def test_PD09_original_release_hold_survives_dispatch_cleanup_return(self):
        self.dispatch_once()
        broker = _OriginalHTTPRequests(object())
        broker._requests[self.original.socket] = self.original
        self.assertFalse(broker._release(self.original.socket, True))
        self.assertIs(broker._requests[self.original.socket], self.original)
        self.assertIs(self.original.handler, self.handler)
        self.assertFalse(broker._live)

    def test_PD10_unrelated_unknown_operation_never_calls_profile_cleanup(self):
        self.original.operation = 'not-a-route'
        self.dispatch_once(); self.assertEqual(self.events, [])
        self.assertEqual(len(self.refusals), 1)
