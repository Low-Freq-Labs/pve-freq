"""Fictional counter/index transitions; no original writer or native grant."""
import builtins
import unittest
from unittest.mock import patch

from test_guest_inventory_child_reservation_data import InventoryChildReservationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_child_reservation_data as reservation
from freq.services import pilot_guest_inventory_commit_data as source


class InventoryCommitData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildReservationData()
        self.fixture.setUp()
        self.owner = self.fixture.fixture.owner

    def duty(self, count=2):
        duty = self.fixture.duty(count)
        reservation.reserve_inventory_children_data(duty)
        candidates = tuple(format(i + 1, '064x') for i in range(count))
        children.prepare_inventory_guest_records_data(duty.batch, candidates)
        return duty

    def snapshot(self, duty):
        return (dict(self.owner._guest_reference_records), dict(duty.ledger),
                duty.ticket._state, duty.ticket._remaining, duty.phase,
                duty.capacity._uncertain, duty.begin.record._spent)

    def test_IC01_whole_ordered_batch_commits_same_retained_records(self):
        duty = self.duty()
        source.commit_inventory_children_data(duty)
        self.assertEqual(duty.phase, 'issued')
        self.assertEqual(duty.ticket._state, 'committed')
        self.assertEqual(duty.ticket._remaining, 2)
        self.assertEqual(duty.capacity._check()[0], 4)
        rows = self.owner._guest_reference_records
        for record in duty.batch.records:
            self.assertIs(rows[(id(duty.begin.session), 'guest', record._key)], record)
        self.assertEqual(duty.batch.phase, 'prepared')
        self.assertTrue(duty.begin.record._spent)

    def test_IC02_empty_batch_settles_only_its_zero_ticket(self):
        duty = self.duty(0)
        rows = dict(self.owner._guest_reference_records)
        source.commit_inventory_children_data(duty)
        self.assertEqual(duty.phase, 'issued')
        self.assertEqual(duty.ticket._state, 'retired')
        self.assertNotIn(id(duty.ticket), duty.ledger)
        self.assertEqual(self.owner._guest_reference_records, rows)
        self.assertEqual(duty.capacity._check()[0], 2)
        self.assertIsNone(reservation.retire_inventory_child_reservation_data(duty, None))
        self.assertEqual(duty.phase, 'retired')

    def test_IC03_late_collision_leaves_whole_preflight_unchanged(self):
        duty = self.duty()
        record = duty.batch.records[-1]
        begin = duty.begin
        ticket = duty.capacity._reserve(begin.session, begin.values[0], 1)
        existing = _GuestReferenceRecord(record._key, 'guest', begin.session,
            begin.values[0], begin.source, begin.generation, begin.cohort,
            ('fixture-node', 'qemu', 999), 111.0, 120.0, ticket, begin.family)
        duty.capacity._commit(ticket)
        self.owner._guest_reference_records[(id(duty.begin.session), 'guest', record._key)] = existing
        before = self.snapshot(duty)
        with self.assertRaises(_RequestUnavailable):
            source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)

    def test_IC04_issued_batch_cannot_commit_twice(self):
        duty = self.duty()
        source.commit_inventory_children_data(duty)
        before = self.snapshot(duty)
        with self.assertRaises(_RequestUnavailable): source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)

    def test_IC05_unknown_commit_return_keeps_charge_and_pending_once_state(self):
        duty = self.duty()
        control, commit = KeyboardInterrupt('fixture lost commit return'), _GuestCapacity._commit
        def lost(capacity, ticket):
            commit(capacity, ticket)
            raise control
        with patch.object(_GuestCapacity, '_commit', lost):
            with self.assertRaises(KeyboardInterrupt) as caught: source.commit_inventory_children_data(duty)
        self.assertIs(caught.exception, control)
        self.assertEqual(duty.phase, 'publication-pending')
        self.assertEqual(duty.ticket._state, 'committed')
        self.assertIs(duty.ledger[id(duty.ticket)], duty.ticket)
        self.assertTrue(duty.capacity._uncertain)
        before = self.snapshot(duty)
        with self.assertRaises(Exception): source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)

    def test_IC06_partial_index_interruption_keeps_known_prefix_for_cleanup(self):
        duty = self.duty()
        control = KeyboardInterrupt('fixture after first indexed holder')
        def interrupted(*args):
            for index, pair in enumerate(builtins.zip(*args)):
                if index == 1: raise control
                yield pair
        # Test-only loop seam; original production inputs remain exact dicts.
        with patch.object(source, 'zip', interrupted, create=True):
            with self.assertRaises(KeyboardInterrupt) as caught: source.commit_inventory_children_data(duty)
        self.assertIs(caught.exception, control)
        rows = self.owner._guest_reference_records
        first, last = duty.batch.records
        self.assertIs(rows[(id(duty.begin.session), 'guest', first._key)], first)
        self.assertNotIn((id(duty.begin.session), 'guest', last._key), rows)
        self.assertEqual(duty.phase, 'publication-pending')
        self.assertTrue(duty.capacity._uncertain)
        self.assertIsNone(reservation.retire_inventory_child_reservation_data(duty, None))
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertNotIn(id(duty.ticket), duty.ledger)
        self.assertEqual(duty.phase, 'retired')
        self.assertTrue(duty.capacity._uncertain)

    def test_IC07_failure_before_ticket_commit_never_indexes_or_retries(self):
        duty = self.duty()
        failure = MemoryError('fixture before capacity commit')
        rows = dict(self.owner._guest_reference_records)
        with patch.object(_GuestCapacity, '_commit', side_effect=failure):
            with self.assertRaises(MemoryError) as caught: source.commit_inventory_children_data(duty)
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.owner._guest_reference_records, rows)
        self.assertEqual(duty.ticket._state, 'reserved')
        self.assertEqual(duty.phase, 'publication-pending')
        self.assertIs(duty.ledger[id(duty.ticket)], duty.ticket)
        # Unknown attempted commit is not guessed as unpublished/refunded.
        self.assertIsInstance(reservation.retire_inventory_child_reservation_data(duty, None), Exception)
        self.assertIs(duty.ledger[id(duty.ticket)], duty.ticket)

    def test_IC08_full_commit_known_cleanup_preserves_prior_control(self):
        duty = self.duty()
        source.commit_inventory_children_data(duty)
        control = KeyboardInterrupt('fixture prior body control')
        self.assertIs(reservation.retire_inventory_child_reservation_data(duty, control), control)
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertNotIn(id(duty.ticket), duty.ledger)
        acquisition = duty.acquisition
        self.assertIs(self.owner._native_guest_inventory_attempts[acquisition.original], acquisition)
        self.assertEqual(acquisition.charge, 15442019)

    def test_IC09_replaced_index_refuses_without_repair(self):
        duty = self.duty()
        saved = self.owner._guest_reference_records
        self.owner._guest_reference_records = dict(saved)
        before = self.snapshot(duty)
        with self.assertRaises(_RequestUnavailable): source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)
        self.assertIs(duty.component_tables[7], saved)

    def test_IC10_missing_pending_ticket_refuses_without_adoption(self):
        duty = self.duty()
        del duty.ledger[id(duty.ticket)]
        before = self.snapshot(duty)
        with self.assertRaises(_RequestUnavailable): source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)

    def test_IC11_foreign_duty_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign duty hook')
        with self.assertRaises(_RequestUnavailable): source.commit_inventory_children_data(Trap())

    def test_IC12_max256_batch_commits_whole_without_source_refund(self):
        duty = self.duty(256)
        source.commit_inventory_children_data(duty)
        self.assertEqual(len(self.owner._guest_reference_records), 257)
        self.assertEqual(duty.ticket._remaining, 256)
        self.assertEqual(duty.capacity._check()[0], 258)
        self.assertTrue(duty.begin.record._spent)

    def test_IC13_incomplete_preparation_refuses_before_commit(self):
        duty = self.duty()
        duty.batch.records.pop()
        before = self.snapshot(duty)
        with self.assertRaises(_RequestUnavailable): source.commit_inventory_children_data(duty)
        self.assertEqual(self.snapshot(duty), before)

    def test_IC14_unknown_empty_settlement_keeps_terminal_ticket_no_retry(self):
        duty = self.duty(0)
        settle = _GuestCapacity._retire_empty_committed
        failure = MemoryError('fixture lost empty settlement return')
        def lost(capacity, ticket):
            settle(capacity, ticket)
            raise failure
        with patch.object(_GuestCapacity, '_retire_empty_committed', lost):
            with self.assertRaises(MemoryError) as caught: source.commit_inventory_children_data(duty)
        self.assertIs(caught.exception, failure)
        self.assertEqual(duty.phase, 'publication-pending')
        self.assertEqual(duty.ticket._state, 'retired')
        self.assertNotIn(id(duty.ticket), duty.ledger)
        self.assertTrue(duty.capacity._uncertain)
        self.assertIsNone(reservation.retire_inventory_child_reservation_data(duty, None))
        self.assertTrue(duty.capacity._uncertain)


# No original admission, native invocation, concurrent writer or physical proof.
