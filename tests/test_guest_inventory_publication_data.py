"""UNRUN fictional whole index DATA cases; no original issuer transaction."""
import unittest

from test_guest_inventory_children_data import InventoryChildrenData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_publication_data as source


class InventoryPublicationData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildrenData()
        self.fixture.setUp()
        self.owner = self.fixture.fixture.owner
        self.owner._original_guest_capacity = self.owner._guest_capacity

    def batch(self, count=2):
        batch = self.fixture.batch(count)
        children.prepare_inventory_guest_records_data(batch,self.fixture.keys(count))
        return batch

    def existing(self, key, purpose='guest', foreign=False):
        begin = self.fixture.begin
        session, family = begin.session, begin.family
        capacity = self.owner._guest_capacity
        if foreign:
            session = {}
            family_ticket = capacity._reserve(session,begin.values[0],1)
            family = _GuestFamilyRecord(session,begin.values[0],'d'*64,
                begin.cohort,begin.generation,object(),90.0,120.0,family_ticket)
            capacity._commit(family_ticket)
            family._bind_once('e'*64)
        ticket = capacity._reserve(session,begin.values[0],1)
        record = _GuestReferenceRecord(key,purpose,session,begin.values[0],
            begin.source,begin.generation,begin.cohort,
            None if purpose=='source' else ('fixture-node','qemu',999),
            110.0,120.0,ticket,family)
        capacity._commit(ticket)
        self.owner._guest_reference_records[(id(session),purpose,key)] = record
        return record

    def snapshot(self, batch):
        return (dict(self.owner._guest_reference_records),
            dict(self.owner._guest_capacity._tickets),batch.ticket._state,
            batch.ticket._remaining,batch.phase,batch.begin.record._spent)

    def test_IP01_whole_ordered_guest_keys_leave_rows_ticket_source_unchanged(self):
        batch = self.batch()
        before = self.snapshot(batch)
        keys = source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(keys,tuple((id(batch.begin.session),'guest',key)
            for key in self.fixture.keys()))
        self.assertEqual(self.snapshot(batch),before)

    def test_IP02_late_collision_refuses_whole_without_partial_insert(self):
        batch = self.batch()
        self.existing(batch.candidates[-1])
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP03_spent_and_retired_guest_keys_are_still_occupied(self):
        batch = self.batch()
        record = self.existing(batch.candidates[0])
        record._consume_once(111.0)
        record._retire()
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP04_equal_source_purpose_key_is_separate_domain(self):
        batch = self.batch()
        record = self.existing(batch.candidates[0],purpose='source')
        before = self.snapshot(batch)
        keys = source.inventory_publication_keys_data(self.owner,batch)
        self.assertIn((id(batch.begin.session),'guest',record._key),keys)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP05_equal_guest_key_in_distinct_session_is_separate_domain(self):
        batch = self.batch()
        record = self.existing(batch.candidates[0],foreign=True)
        before = self.snapshot(batch)
        keys = source.inventory_publication_keys_data(self.owner,batch)
        self.assertIsNot(record._session,batch.begin.session)
        self.assertIn((id(batch.begin.session),'guest',record._key),keys)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP06_reserved_existing_row_ticket_refuses_without_guess_commit(self):
        batch = self.batch()
        record = self.existing('f'*64)
        record._ticket._state = 'reserved'
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)
        self.assertEqual(record._ticket._state,'reserved')

    def test_IP07_missing_same_pending_ticket_refuses_without_adoption(self):
        batch = self.batch()
        del self.owner._guest_capacity._tickets[id(batch.ticket)]
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP08_present_None_existing_row_refuses_without_delete(self):
        batch = self.batch()
        key = (id(batch.begin.session),'guest','f'*64)
        self.owner._guest_reference_records[key] = None
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)
        self.assertIsNone(self.owner._guest_reference_records[key])

    def test_IP09_whole_size_filter_refuses_before_any_insert(self):
        batch = self.batch()
        # Seeded size-filter DATA only, deliberately not coherent original rows.
        self.owner._guest_reference_records.update({i:None for i in range(4094)})
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP10_empty_keys_leave_explicit_zero_ticket_reserved(self):
        batch = self.batch(0)
        before = self.snapshot(batch)
        self.assertEqual(source.inventory_publication_keys_data(self.owner,batch),())
        self.assertEqual(self.snapshot(batch),before)
        self.assertEqual(batch.ticket._state,'reserved')

    def test_IP11_foreign_batch_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign batch hook')
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,Trap())

    def test_IP12_replaced_original_index_pointer_refuses_without_repair(self):
        batch = self.batch()
        old = self.owner._guest_reference_records
        self.owner._guest_reference_records = dict(old)
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)
        self.assertEqual(self.owner._original_component_tables[7],old)
        self.assertIs(self.owner._original_component_tables[7],old)

    def test_IP13_corrupted_candidate_and_matching_private_key_still_refuse(self):
        batch = self.batch()
        batch.candidates = ('g'*64,batch.candidates[1])
        batch.records[0]._key = batch.candidates[0]
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)

    def test_IP14_corrupted_duplicate_candidates_cannot_return_duplicate_keys(self):
        batch = self.batch()
        batch.candidates = (batch.candidates[0],batch.candidates[0])
        batch.records[1]._key = batch.candidates[0]
        before = self.snapshot(batch)
        with self.assertRaises(_RequestUnavailable):
            source.inventory_publication_keys_data(self.owner,batch)
        self.assertEqual(self.snapshot(batch),before)
