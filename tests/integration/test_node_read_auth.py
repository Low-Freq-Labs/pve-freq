"""Prepared application session fixtures; no provider authentication proof."""
import threading
import unittest
from unittest.mock import patch

from freq.api import auth
from freq.services.node_read_auth import NodeSessionIssuer, capture_node_session
from freq.services.node_read_profile import WireTarget
from freq.services.node_read_registry import NodeReadRegistry, TargetSpec, LeaseSlot
from freq.services.node_read_references import NodeReadReferences


class NodeAuthTests(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        self.session = {"user": "fixture", "role": "viewer", "ts": 10.0}
        self.sessions = {"fictional-session": self.session}
        for target, value in (("_auth_lock", self.lock), ("_auth_tokens", self.sessions)):
            p = patch.object(auth, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(auth, "_extract_session_token", return_value="fictional-session")
        p.start()
        self.addCleanup(p.stop)
        p = patch("freq.services.node_read_auth.time.time", return_value=20.0)
        p.start()
        self.addCleanup(p.stop)
        self.registry = NodeReadRegistry()
        self.registry.publish((TargetSpec(
            "node", WireTarget("192.0.2.1", "node.invalid", "node"),
            "supplied-node-network-list-v1", "trust-v1", 0, 0,
            object(), object(), object()),))
        self.references = NodeReadReferences(self.registry)
        self.issuer = NodeSessionIssuer(self.registry, self.references)
        self.grant = capture_node_session(object())

    def test_original_application_session_issues_and_consumes(self):
        selection = self.issuer.issue_selection(self.grant, "node")
        binding, remaining = self.issuer.bind(self.grant, selection)
        self.assertGreater(remaining, 0)
        lease = LeaseSlot()
        self.issuer.consume_into(self.grant, binding, lease)
        self.assertTrue(self.registry.current(lease))
        lease.release()

    def test_equal_session_replacement_refuses(self):
        self.sessions["fictional-session"] = dict(self.session)
        with self.assertRaises(ValueError):
            self.issuer.issue_selection(self.grant, "node")
        self.assertEqual(self.registry._references, 0)

    def test_logout_refuses_without_spending_foreign_binding(self):
        selection = self.issuer.issue_selection(self.grant, "node")
        binding, _ = self.issuer.bind(self.grant, selection)
        del self.sessions["fictional-session"]
        with self.assertRaises(ValueError):
            self.issuer.consume_into(self.grant, binding, LeaseSlot())
        self.assertIn(binding, self.references._entries)

    def test_role_user_and_store_replacement_refuse(self):
        for field in ("role", "user"):
            original = self.session[field]
            self.session[field] = "changed"
            with self.assertRaises(ValueError):
                self.issuer.issue_selection(self.grant, "node")
            self.session[field] = original
        with patch.object(auth, "_auth_tokens", dict(self.sessions)):
            with self.assertRaises(ValueError):
                self.issuer.issue_selection(self.grant, "node")

    def test_original_expiry_not_renewed_by_session_touch(self):
        self.session["last_activity_ts"] = self.grant.expires - 1
        with patch("freq.services.node_read_auth.time.time", return_value=self.grant.expires):
            with self.assertRaises(ValueError):
                self.issuer.issue_selection(self.grant, "node")

    def test_cleanup_after_auth_lock_and_invocation_remains_original(self):
        selection = self.issuer.issue_selection(self.grant, "node")
        binding, _ = self.issuer.bind(self.grant, selection)
        lease = LeaseSlot()
        original = LeaseSlot.release
        def checked_release(slot):
            self.assertFalse(self.lock.locked())
            original(slot)
            raise RuntimeError("fixture uncertain cleanup")
        with patch.object(LeaseSlot, "release", checked_release):
            with self.assertRaises(RuntimeError):
                self.issuer.consume_into(self.grant, binding, lease)
        self.assertTrue(self.registry.current(lease))
        lease.release()

    def test_operation_genuine_survives_cleanup_genuine(self):
        class Genuine(BaseException):
            pass
        first, later = Genuine(), Genuine()
        acquire = NodeReadRegistry._acquire_record_locked
        release = LeaseSlot.release
        def acquire_then_fail(registry, slot, record, kind):
            acquire(registry, slot, record, kind)
            raise first
        def release_then_fail(slot):
            self.assertFalse(self.lock.locked())
            release(slot)
            raise later
        with patch.object(NodeReadRegistry, "_acquire_record_locked", acquire_then_fail):
            with patch.object(LeaseSlot, "release", release_then_fail):
                with self.assertRaises(Genuine) as caught:
                    self.issuer.issue_selection(self.grant, "node")
        self.assertIs(caught.exception, first)
        self.assertEqual(self.registry._references, 0)

    def test_operation_capacity_refuses_before_reference_effect(self):
        for _ in range(64):
            self.assertTrue(self.issuer._operations.acquire(blocking=False))
        with self.assertRaises(ValueError):
            self.issuer.issue_selection(self.grant, "node")
        self.assertEqual(self.registry._references, 0)
        for _ in range(64):
            self.issuer._operations.release()

    def test_invalid_session_scalar_types_refuse_capture(self):
        for field, invalid in (("role", []), ("user", object()), ("ts", True),
                               ("ts", float("nan")), ("ts", 10 ** 1000)):
            original = self.session[field]
            self.session[field] = invalid
            self.assertIsNone(capture_node_session(object()))
            self.session[field] = original


    def test_clock_helper_logout_cannot_pass_original_session_fence(self):
        def logout_then_return():
            self.sessions.clear()
            return 20.0
        with patch("freq.services.node_read_auth.time.time", side_effect=logout_then_return):
            with self.assertRaises(ValueError):
                self.issuer.issue_selection(self.grant, "node")
        self.assertEqual(self.registry._references, 0)
