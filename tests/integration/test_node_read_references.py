"""Prepared reference/registry join fixtures. No authentication or TLS proof."""
import threading
import unittest
from unittest.mock import patch

from freq.services.node_read_profile import WireTarget
from freq.services.node_read_registry import NodeReadRegistry, TargetSpec, LeaseSlot
from freq.services.node_read_references import NodeReadReferences, ReferenceCleanup


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.registry = NodeReadRegistry()
        self.spec = TargetSpec(
            "node", WireTarget("192.0.2.1", "node.invalid", "node"),
            "supplied-node-network-list-v1", "trust-v1", 0, 0,
            object(), object(), object())
        self.registry.publish((self.spec,))
        self.store = NodeReadReferences(self.registry)
        self.session = {}

    def binding(self):
        selected = self.store.issue_selection(self.session, "node")
        return self.store.bind(self.session, selected)[0]

    def test_equal_session_does_not_spend_original_binding(self):
        ref = self.binding()
        with self.assertRaises(ValueError):
            self.store.consume_into({}, ref, LeaseSlot())
        lease = LeaseSlot()
        self.store.consume_into(self.session, ref, lease)
        self.assertTrue(self.registry.current(lease))
        lease.release()

    def test_replaced_registry_refuses_and_spends_binding(self):
        ref = self.binding()
        self.registry.publish((self.spec,))
        lease = LeaseSlot()
        with self.assertRaises(ValueError):
            self.store.consume_into(self.session, ref, lease)
        self.assertIsNone(lease._registry)
        self.assertNotIn(ref, self.store._entries)
        self.store.retire(self.session)
        self.registry.publish((self.spec,))

    def test_binding_does_not_extend_selection_expiry(self):
        with patch("freq.services.node_read_references.time.monotonic", return_value=10):
            selection = self.store.issue_selection(self.session, "node")
        with patch("freq.services.node_read_references.time.monotonic", return_value=39):
            ref, remaining = self.store.bind(self.session, selection)
        self.assertEqual(remaining, 1000)
        with patch("freq.services.node_read_references.time.monotonic", return_value=40):
            with self.assertRaises(ValueError):
                self.store.consume_into(self.session, ref, LeaseSlot())
        self.assertNotIn(ref, self.store._entries)

    def test_lost_outer_return_keeps_invocation_duty(self):
        ref = self.binding()
        lease = LeaseSlot()
        def acquire_then_fail():
            self.store.consume_into(self.session, ref, lease)
            raise RuntimeError("fixture lost return")
        with self.assertRaises(RuntimeError):
            acquire_then_fail()
        self.assertEqual(self.registry._invocations, 1)
        with self.assertRaises(ValueError):
            self.store.consume_into(self.session, ref, LeaseSlot())
        lease.release()
        self.assertEqual(self.registry._invocations, 0)

    def test_selection_and_binding_session_caps(self):
        selections = [self.store.issue_selection(self.session, "node")
                      for _ in range(64)]
        with self.assertRaises(ValueError):
            self.store.issue_selection(self.session, "node")
        for _ in range(16):
            self.store.bind(self.session, selections[0])
        with self.assertRaises(ValueError):
            self.store.bind(self.session, selections[0])
        self.assertEqual(self.registry._references, 80)
        self.store.retire(self.session)
        self.assertEqual(self.registry._references, 0)

    def test_process_capacity_preserves_live_entries(self):
        sessions = [{} for _ in range(16)]
        for session in sessions:
            for _ in range(64):
                self.store.issue_selection(session, "node")
        with self.assertRaises(ValueError):
            self.store.issue_selection({}, "node")
        self.assertEqual(len(self.store._entries), 1024)
        self.assertEqual(self.registry._references, 1024)

    def test_retired_session_keeps_active_invocation_lease(self):
        ref = self.binding()
        lease = LeaseSlot()
        self.store.consume_into(self.session, ref, lease)
        self.registry.publish((self.spec,))
        self.store.retire(self.session)
        self.assertEqual(self.registry._references, 0)
        self.assertEqual(self.registry._invocations, 1)
        with self.assertRaises(ValueError):
            self.registry.publish((self.spec,))
        lease.release()
        self.registry.publish((self.spec,))

    def test_full_invocation_capacity_still_spends_owned_binding(self):
        leases = [LeaseSlot() for _ in range(64)]
        for lease in leases:
            self.registry.acquire_into(lease, "node", "invocation")
        ref = self.binding()
        with self.assertRaises(ValueError):
            self.store.consume_into(self.session, ref, LeaseSlot())
        self.assertNotIn(ref, self.store._entries)
        for lease in leases:
            lease.release()

    def test_binding_release_fault_keeps_published_invocation_duty(self):
        ref = self.binding()
        lease = LeaseSlot()
        original_release = LeaseSlot.release
        def release_then_fail(slot):
            original_release(slot)
            raise RuntimeError("fixture uncertain release")
        with patch.object(LeaseSlot, "release", release_then_fail):
            with self.assertRaises(RuntimeError):
                self.store.consume_into(self.session, ref, lease)
        self.assertTrue(self.registry.current(lease))
        self.assertNotIn(ref, self.store._entries)
        lease.release()

    def test_first_genuine_survives_later_cleanup_genuine(self):
        class FixtureGenuine(BaseException):
            pass
        first, later = FixtureGenuine(), FixtureGenuine()
        ref = self.binding()
        original_release = LeaseSlot.release
        def release_then_fail(slot):
            original_release(slot)
            raise later
        with patch("freq.services.node_read_references.time.monotonic", side_effect=first):
            with patch.object(LeaseSlot, "release", release_then_fail):
                with self.assertRaises(FixtureGenuine) as caught:
                    self.store.consume_into(self.session, ref, LeaseSlot())
        self.assertIs(caught.exception, first)
        self.assertNotIn(ref, self.store._entries)


    def test_authenticated_consume_defers_original_release(self):
        ref = self.binding()
        lease, cleanup = LeaseSlot(), ReferenceCleanup()
        auth_lock = threading.Lock()
        original_release = LeaseSlot.release
        calls = []
        def checked_release(slot):
            self.assertFalse(auth_lock.locked())
            calls.append(slot)
            original_release(slot)
        with patch.object(LeaseSlot, "release", checked_release):
            with auth_lock:
                self.store.consume_into(self.session, ref, lease, cleanup=cleanup)
                self.assertEqual(calls, [])
                self.assertEqual(self.registry._references, 2)
            cleanup.drain()
            cleanup.drain()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.registry._references, 1)
        lease.release()

    def test_deferred_expired_consume_keeps_cleanup_duty(self):
        ref = self.binding()
        cleanup = ReferenceCleanup()
        with patch("freq.services.node_read_references.time.monotonic", return_value=float("inf")):
            with self.assertRaises(ValueError):
                self.store.consume_into(self.session, ref, LeaseSlot(), cleanup=cleanup)
        self.assertNotIn(ref, self.store._entries)
        self.assertEqual(self.registry._references, 2)
        cleanup.drain()
        self.assertEqual(self.registry._references, 1)

    def test_deferred_issue_lost_acquisition_return(self):
        cleanup = ReferenceCleanup()
        original = NodeReadRegistry._acquire_record_locked
        def acquire_then_fail(registry, slot, record, kind):
            original(registry, slot, record, kind)
            raise RuntimeError("fixture lost return")
        with patch.object(NodeReadRegistry, "_acquire_record_locked", acquire_then_fail):
            with self.assertRaises(RuntimeError):
                self.store.issue_selection(self.session, "node", cleanup=cleanup)
        self.assertEqual(len(self.store._entries), 0)
        self.assertEqual(self.registry._references, 1)
        cleanup.drain()
        self.assertEqual(self.registry._references, 0)

    def test_deferred_retirement_keeps_all_original_duties(self):
        self.binding()
        cleanup = ReferenceCleanup()
        self.store.retire(self.session, cleanup=cleanup)
        self.assertEqual(len(self.store._entries), 0)
        self.assertEqual(self.registry._references, 2)
        cleanup.drain()
        self.assertEqual(self.registry._references, 0)

    def test_deferred_cleanup_attempts_all_and_keeps_first_genuine(self):
        class Genuine(BaseException):
            pass
        first, second = Genuine(), Genuine()
        self.binding()
        cleanup = ReferenceCleanup()
        self.store.retire(self.session, cleanup=cleanup)
        original = LeaseSlot.release
        calls = []
        def release_then_fail(slot):
            original(slot)
            calls.append(slot)
            raise first if len(calls) == 1 else second
        with patch.object(LeaseSlot, "release", release_then_fail):
            with self.assertRaises(Genuine) as caught:
                cleanup.drain()
            cleanup.drain()
        self.assertIs(caught.exception, first)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.registry._references, 0)

    def test_cleanup_owner_cannot_be_reused(self):
        cleanup = ReferenceCleanup()
        self.store.issue_selection(self.session, "node", cleanup=cleanup)
        with self.assertRaises(ValueError):
            self.store.issue_selection(self.session, "node", cleanup=cleanup)
        cleanup.drain()
        self.assertEqual(self.registry._references, 1)


    def test_retirement_retains_detached_session_until_outside_lock(self):
        events = []
        auth_lock = threading.Lock()
        class Witness:
            def __del__(self):
                events.append(auth_lock.locked())
        session = {"fixture": Witness()}
        self.store.issue_selection(session, "node")
        del session
        cleanup = ReferenceCleanup()
        with patch("freq.services.node_read_references.time.monotonic", return_value=float("inf")):
            with auth_lock:
                self.store.retire(cleanup=cleanup)
                self.assertEqual(events, [])
        cleanup.drain()
        self.assertEqual(events, [False])
