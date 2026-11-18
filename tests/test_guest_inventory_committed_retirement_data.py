"""UNRUN seeded publication/retirement DATA, not actual guarded controls."""
import unittest
from unittest.mock import patch

from test_guest_inventory_child_reservation_data import InventoryChildReservationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_child_reservation_data as counter
from freq.services import pilot_guest_inventory_committed_retirement_data as source


class InventoryCommittedRetirementData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildReservationData()
        self.fixture.setUp()
        self.owner = self.fixture.fixture.owner

    def duty(self, count=2, indexed=None):
        duty = self.fixture.duty(count)
        counter.reserve_inventory_children_data(duty)
        children.prepare_inventory_guest_records_data(duty.batch,
            tuple(format(i+1,'064x') for i in range(count)))
        duty.capacity._commit(duty.ticket)
        rows = self.owner._guest_reference_records
        for record in duty.batch.records[:count if indexed is None else indexed]:
            rows[(id(record._session),'guest',record._key)] = record
        return duty

    def test_CT01_whole_indexed_records_retire_then_same_ticket_settles(self):
        duty = self.duty()
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertEqual(duty.ticket._state,'retired')
        self.assertEqual(duty.ticket._remaining,0)
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(duty.phase,'retired')
        self.assertEqual(len(self.owner._guest_reference_records),1)
        self.assertIs(self.owner._native_guest_inventory_attempts[
            duty.acquisition.original],duty.acquisition)
        self.assertEqual(duty.acquisition.charge,15442019)

    def test_CT02_seeded_partial_index_has_whole_known_private_record_set(self):
        duty = self.duty(indexed=1)
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertEqual(duty.ticket._remaining,0)
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CT03_committed_but_unindexed_known_batch_can_settle(self):
        duty = self.duty(indexed=0)
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(len(self.owner._guest_reference_records),1)

    def test_CT04_explicit_committed_zero_ticket_settles(self):
        duty = self.duty(0)
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertEqual(duty.ticket._state,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CT05_own_uncertainty_and_expired_family_do_not_skip_known_cleanup(self):
        duty = self.duty()
        duty.capacity._uncertain = True
        duty.begin.family._retire()
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertTrue(duty.capacity._uncertain)
        self.assertEqual(duty.ticket._state,'retired')

    def test_CT06_prior_body_control_preserved_after_independent_settlement(self):
        duty = self.duty()
        control = KeyboardInterrupt('fictional earlier body control')
        self.assertIs(source.retire_inventory_committed_children_data(duty,control),control)
        self.assertEqual(duty.ticket._state,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CT07_holder_control_attempts_later_record_but_never_refunds(self):
        duty = self.duty()
        control = KeyboardInterrupt('fictional first child control')
        original = _GuestReferenceRecord._retire
        seen = []
        def retire(record):
            seen.append(record)
            if record is duty.batch.records[0]: raise control
            return original(record)
        before = dict(self.owner._guest_reference_records)
        with patch.object(_GuestReferenceRecord,'_retire',retire):
            error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIs(error,control)
        self.assertEqual(seen,duty.batch.records)
        self.assertTrue(duty.batch.records[1]._retired)
        self.assertEqual(self.owner._guest_reference_records,before)
        self.assertEqual(duty.ticket._state,'committed')
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)

    def test_CT08_foreign_same_key_kept_while_later_known_row_removed(self):
        duty = self.duty()
        rows = self.owner._guest_reference_records
        first = duty.batch.records[0]
        key = (id(first._session),'guest',first._key)
        replacement = self.fixture.fixture.record
        rows[key] = replacement
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertIs(rows[key],replacement)
        second = duty.batch.records[1]
        self.assertNotIn((id(second._session),'guest',second._key),rows)
        self.assertEqual(duty.ticket._state,'committed')
        self.assertEqual(duty.phase,'indexed-retire-attempted')
        self.assertTrue(duty.capacity._uncertain)

    def test_CT09_hidden_same_ticket_row_keeps_ticket_charged(self):
        duty = self.duty()
        rows = self.owner._guest_reference_records
        rows[(id(duty.begin.session),'guest','f'*64)] = duty.batch.records[0]
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertEqual(duty.ticket._remaining,2)
        self.assertEqual(len(rows),2)

    def test_CT10_incomplete_known_list_retires_known_but_does_not_settle(self):
        duty = self.duty()
        duty.batch.records.pop()
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertTrue(duty.batch.records[0]._retired)
        self.assertEqual(duty.ticket._state,'committed')
        self.assertEqual(duty.ticket._remaining,2)

    def test_CT11_known_family_settled_ticket_is_recognized_without_positive_flags(self):
        duty = self.duty()
        rows = self.owner._guest_reference_records
        for record in duty.batch.records:
            record._retire()
            del rows[(id(record._session),'guest',record._key)]
            duty.capacity._release_retired_records(duty.ticket,1)
        duty.capacity._uncertain = True
        duty.begin.family._retire()
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertEqual(duty.phase,'retired')
        self.assertTrue(duty.capacity._uncertain)
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CT12_complete_retirement_repeat_does_not_touch_other_tickets(self):
        duty = self.duty()
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        rows, ledger = dict(self.owner._guest_reference_records),dict(duty.ledger)
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertEqual(self.owner._guest_reference_records,rows)
        self.assertEqual(duty.ledger,ledger)

    def test_CT13_seeded_unknown_mutation_phase_cannot_retry_or_refund(self):
        duty = self.duty()
        duty.phase = 'indexed-retire-attempted'  # Seeded DATA, no observed interruption.
        rows = dict(self.owner._guest_reference_records)
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertEqual(self.owner._guest_reference_records,rows)
        self.assertEqual(duty.ticket._state,'committed')
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)

    def test_CT14_reserved_unpublished_ticket_is_not_guessed_committed(self):
        duty = self.duty(indexed=0)
        duty.ticket._state = 'reserved'
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertEqual(duty.ticket._state,'reserved')
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)

    def test_CT15_unknown_cleanup_phase_cannot_repair_even_seeded_terminal_ticket(self):
        duty = self.duty(indexed=0)
        duty.phase = 'indexed-retire-attempted'
        duty.ticket._remaining = 0
        duty.ticket._state = 'retired'
        del duty.ledger[id(duty.ticket)]
        error = source.retire_inventory_committed_children_data(duty,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertEqual(duty.phase,'indexed-retire-attempted')
        self.assertTrue(duty.capacity._uncertain)

    def test_CT16_seeded_partial_family_settlement_binds_remaining_whole_holders(self):
        duty = self.duty()
        record = duty.batch.records[0]
        record._retire()
        del self.owner._guest_reference_records[(id(record._session),'guest',record._key)]
        duty.capacity._release_retired_records(duty.ticket,1)
        self.assertEqual(duty.ticket._remaining,1)
        duty.begin.family._retire()
        self.assertIsNone(source.retire_inventory_committed_children_data(duty,None))
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertEqual(duty.ticket._remaining,0)
        self.assertNotIn(id(duty.ticket),duty.ledger)
