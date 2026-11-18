"""Request-reference ownership checks; no provider or network access."""
import concurrent.futures
import unittest
from unittest.mock import patch

from freq.services.cluster_references import (
    ClusterReferences, ReferenceUnavailable, TargetSnapshot,
)


class ClusterReferenceTests(unittest.TestCase):
    def setUp(self):
        self.store = ClusterReferences()
        self.session = {'user': 'fixture', 'role': 'viewer'}
        self.target = TargetSnapshot('revision-a', 'configured-node-a', 'fixture.invalid')

    def selection(self):
        return self.store.issue_selection(self.session, self.target)

    def test_one_consumer_wins_concurrent_reuse(self):
        binding, _ = self.store.bind(self.session, self.selection(), 'revision-a')
        def consume(_):
            try:
                return self.store.consume(self.session, binding, 'revision-a')
            except ReferenceUnavailable:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(16)))
        self.assertEqual(sum(result is self.target for result in results), 1)
        self.assertEqual(results.count(None), 15)

    def test_same_username_replacement_cannot_bind_or_consume(self):
        replacement = dict(self.session)
        selection = self.selection()
        with self.assertRaises(ReferenceUnavailable):
            self.store.bind(replacement, selection, 'revision-a')
        binding, _ = self.store.bind(self.session, selection, 'revision-a')
        with self.assertRaises(ReferenceUnavailable):
            self.store.consume(replacement, binding, 'revision-a')
        self.assertIs(self.store.consume(self.session, binding, 'revision-a'), self.target)

    def test_configuration_change_spends_owned_binding(self):
        binding, _ = self.store.bind(self.session, self.selection(), 'revision-a')
        with self.assertRaises(ReferenceUnavailable):
            self.store.consume(self.session, binding, 'revision-b')
        with self.assertRaises(ReferenceUnavailable):
            self.store.consume(self.session, binding, 'revision-a')

    def test_binding_never_extends_inventory_expiry(self):
        with patch('freq.services.cluster_references.time.monotonic', return_value=10.0):
            selection = self.selection()
        with patch('freq.services.cluster_references.time.monotonic', return_value=39.0):
            binding, milliseconds = self.store.bind(self.session, selection, 'revision-a')
        self.assertEqual(milliseconds, 1000)
        with patch('freq.services.cluster_references.time.monotonic', return_value=40.0):
            with self.assertRaises(ReferenceUnavailable):
                self.store.consume(self.session, binding, 'revision-a')

    def test_retirement_removes_original_session_references_only(self):
        selection = self.selection()
        binding, _ = self.store.bind(self.session, selection, 'revision-a')
        other = {'user': 'other', 'role': 'viewer'}
        other_selection = self.store.issue_selection(other, self.target)
        self.store.retire_session(self.session)
        with self.assertRaises(ReferenceUnavailable):
            self.store.bind(self.session, selection, 'revision-a')
        with self.assertRaises(ReferenceUnavailable):
            self.store.consume(self.session, binding, 'revision-a')
        other_binding, _ = self.store.bind(other, other_selection, 'revision-a')
        self.assertIs(self.store.consume(other, other_binding, 'revision-a'), self.target)

    def test_capacity_refusal_preserves_existing_references(self):
        selection = self.selection()
        bindings = [self.store.bind(self.session, selection, 'revision-a')[0]
                    for _ in range(self.store.BINDINGS_PER_SESSION)]
        with self.assertRaises(ReferenceUnavailable):
            self.store.bind(self.session, selection, 'revision-a')
        for binding in bindings:
            self.assertIs(self.store.consume(self.session, binding, 'revision-a'), self.target)
        for _ in range(self.store.SELECTIONS_PER_SESSION - 1):
            self.selection()
        with self.assertRaises(ReferenceUnavailable):
            self.selection()
        binding, _ = self.store.bind(self.session, selection, 'revision-a')
        self.assertIs(self.store.consume(self.session, binding, 'revision-a'), self.target)

    def test_browser_target_and_reference_aliases_refused(self):
        for target in ({'endpoint': 'attacker.invalid'}, 'fixture.invalid', None):
            with self.assertRaises(ReferenceUnavailable):
                self.store.issue_selection(self.session, target)
        for reference in ('', 'a' * 31, 'a' * 33, 'A' * 32, None, 1):
            with self.assertRaises(ReferenceUnavailable):
                self.store.bind(self.session, reference, 'revision-a')

    def test_collision_never_replaces_live_reference(self):
        with patch('freq.services.cluster_references.secrets.token_hex', return_value='a' * 32):
            selected = self.selection()
            with self.assertRaises(ReferenceUnavailable):
                self.store.issue_selection({'user': 'other'}, self.target)
        binding, _ = self.store.bind(self.session, selected, 'revision-a')
        self.assertIs(self.store.consume(self.session, binding, 'revision-a'), self.target)
