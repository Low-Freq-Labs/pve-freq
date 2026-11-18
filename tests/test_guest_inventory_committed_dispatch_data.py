"""UNRUN counter/original-shaped cleanup dispatch DATA, no actual four gates."""
import unittest
from unittest.mock import patch

from test_guest_inventory_child_custody_data import InventoryChildCustodyData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_child_reservation_data as counter
from freq.services import pilot_guest_inventory_retirement as original_retirement


class InventoryCommittedDispatchData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildCustodyData()
        self.fixture.setUp()
        self.owner = self.fixture.f.owner
        self.acquisition = self.fixture.acquisition

    def duty(self, count=2, committed=True):
        duty = self.fixture.retained(count)
        counter.reserve_inventory_children_data(duty)
        children.prepare_inventory_guest_records_data(duty.batch,
            tuple(format(i+1,'064x') for i in range(count)))
        if committed:
            duty.capacity._commit(duty.ticket)
            for record in duty.batch.records:
                self.owner._guest_reference_records[
                    (id(record._session),'guest',record._key)] = record
        return duty

    def test_CD01_original_shaped_source_native_child_loop_dispatches_committed_batch(self):
        duty = self.duty()
        self.assertIsNone(original_retirement._retire_unstarted_holders_data(
            self.acquisition,None))
        self.assertTrue(self.fixture.f.record._retired)
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertEqual(duty.phase,'retired')
        self.assertEqual(self.acquisition.children.phase,'retired')
        self.assertIs(self.acquisition.children.reservation,duty)
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertIs(self.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)
        self.assertEqual(self.acquisition.charge,15442019)

    def test_CD02_prior_body_control_does_not_skip_bound_committed_cleanup(self):
        duty = self.duty()
        control = KeyboardInterrupt('fictional earlier body control')
        self.assertIs(original_retirement._retire_unstarted_holders_data(
            self.acquisition,control),control)
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(self.acquisition.children.phase,'retired')

    def test_CD03_source_control_kept_while_later_bound_child_cleanup_settles(self):
        duty = self.duty()
        control = KeyboardInterrupt('fictional source control')
        original = _GuestReferenceRecord._retire
        def retire(record):
            if record is self.fixture.f.record: raise control
            return original(record)
        with patch.object(_GuestReferenceRecord,'_retire',retire):
            error = original_retirement._retire_unstarted_holders_data(
                self.acquisition,None)
        self.assertIs(error,control)
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(self.acquisition.children.phase,'retired')

    def test_CD04_own_uncertainty_and_retired_family_do_not_restore_positive_flags(self):
        duty = self.duty()
        duty.capacity._uncertain = True
        duty.begin.family._retire()
        self.assertIsNone(original_retirement._retire_unstarted_holders_data(
            self.acquisition,None))
        self.assertTrue(duty.capacity._uncertain)
        self.assertEqual(duty.begin.family._state,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CD05_incomplete_holder_set_refuses_without_counter_refund(self):
        duty = self.duty()
        duty.batch.records.pop()
        error = original_retirement._retire_unstarted_holders_data(
            self.acquisition,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertTrue(duty.batch.records[0]._retired)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertEqual(self.acquisition.children.phase,'retained')

    def test_CD06_unpublished_reserved_ticket_keeps_existing_cleanup_path(self):
        duty = self.duty(committed=False)
        self.assertIsNone(original_retirement._retire_unstarted_holders_data(
            self.acquisition,None))
        self.assertTrue(all(record._retired for record in duty.batch.records))
        self.assertEqual(duty.ticket._state,'retired')
        self.assertEqual(duty.ticket._remaining,2)
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(self.acquisition.children.phase,'retired')

    def test_CD07_exact_already_settled_prepared_family_ticket_uses_known_path(self):
        duty = self.duty()
        for record in duty.batch.records:
            record._retire()
            del self.owner._guest_reference_records[
                (id(record._session),'guest',record._key)]
            duty.capacity._release_retired_records(duty.ticket,1)
        self.assertIsNone(original_retirement._retire_unstarted_holders_data(
            self.acquisition,None))
        self.assertEqual(self.acquisition.children.phase,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CD08_seeded_unknown_mutation_dispatch_never_retries_or_clears_native(self):
        duty = self.duty()
        duty.phase = 'indexed-retire-attempted'
        rows = dict(self.owner._guest_reference_records)
        error = original_retirement._retire_unstarted_holders_data(
            self.acquisition,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertEqual(self.owner._guest_reference_records,rows)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertEqual(self.acquisition.children.phase,'retained')
        self.assertIs(self.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)
