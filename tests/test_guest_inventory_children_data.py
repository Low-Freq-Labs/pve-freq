"""UNRUN whole decoded/private guest-holder DATA cases, no original issuance."""
import json
import unittest
from unittest.mock import patch

from test_guest_inventory_registration_data import InventoryRegistrationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_children_data as source


class InventoryChildrenData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryRegistrationData()
        self.fixture.setUp()
        self.begin = self.fixture.duty().begin

    def raw(self, count=2):
        return json.dumps({'data': [dict(type='qemu' if i % 2 == 0 else 'lxc',
            node='fixture-node', vmid=100+i, name='fixture-'+str(i), template=1)
            for i in range(count)]}, separators=(',', ':')).encode('utf-8')

    def batch(self, count=2):
        decoded = source._DecodedGuestRowsData(self.raw(count))
        f = self.fixture
        ticket = f.owner._guest_capacity._reserve(f.session, f.values[0], count)
        return source._InventoryGuestBatchData(self.begin, decoded, ticket, 111.0)

    def keys(self, count=2):
        return tuple(format(i+1, '064x') for i in range(count))

    def test_IC01_whole_decoder_order_kind_template_and_immutable_targets(self):
        decoded = source._DecodedGuestRowsData(self.raw())
        self.assertEqual(decoded.rows, (('fixture-node','qemu',100,'fixture-0'),
            ('fixture-node','lxc',101,'fixture-1')))
        self.assertEqual(decoded.targets, (('fixture-node','qemu',100),
            ('fixture-node','lxc',101)))
        with self.assertRaises(TypeError): decoded.rows = ()
        with self.assertRaises(TypeError): del decoded.targets

    def test_IC02_complete_256_private_records_fit_whole_reserved_DATA_ticket(self):
        batch = self.batch(256)
        source.prepare_inventory_guest_records_data(batch, self.keys(256))
        source.prepared_inventory_guest_records_data(batch)
        self.assertEqual(len(batch.records), 256)
        self.assertEqual(batch.ticket._remaining, 256)
        self.assertEqual(batch.ticket._state, 'reserved')
        self.assertEqual(self.fixture.owner._guest_capacity._check()[0], 258)
        self.assertEqual(len(self.fixture.owner._guest_reference_records), 1)
        self.assertIs(batch.records[255]._target, batch.decoded.targets[255])

    def test_IC03_257_rows_refuse_whole_before_any_child_ticket_or_record(self):
        before = dict(self.fixture.owner._guest_capacity._tickets)
        with self.assertRaises(ValueError): source._DecodedGuestRowsData(self.raw(257))
        self.assertEqual(self.fixture.owner._guest_capacity._tickets, before)
        self.assertEqual(len(self.fixture.owner._guest_reference_records), 1)

    def test_IC04_empty_inventory_has_explicit_unsettled_zero_ticket(self):
        batch = self.batch(0)
        source.prepare_inventory_guest_records_data(batch, ())
        source.prepared_inventory_guest_records_data(batch)
        self.assertEqual(batch.records, [])
        self.assertEqual(batch.ticket._remaining, 0)
        self.assertEqual(batch.ticket._state, 'reserved')
        self.assertIs(self.fixture.owner._guest_capacity._tickets[id(batch.ticket)], batch.ticket)
        self.assertIsNone(source.retire_inventory_guest_records_data(batch, None))
        self.assertEqual(batch.ticket._state, 'reserved')  # No fake zero settlement.

    def test_IC05_duplicate_or_malformed_late_raw_row_refuses_no_partial_batch(self):
        for body in (b'{"data":[{"type":"qemu","node":"n","vmid":100},'
                     b'{"type":"qemu","node":"n","vmid":100}]}',
                     b'{"data":[{"type":"qemu","node":"n","vmid":100},'
                     b'{"type":"node","ignored":{"nested":1}}]}'):
            with self.assertRaises(ValueError): source._DecodedGuestRowsData(body)
        self.assertEqual(self.fixture.owner._guest_capacity._check()[0], 2)

    def test_IC06_whole_candidate_count_and_uniqueness_before_first_record(self):
        for keys in ((self.keys()[0],), (self.keys()[0],)*2, ('g'*64,'2'*64)):
            batch = self.batch()
            with self.assertRaises(_RequestUnavailable):
                source.prepare_inventory_guest_records_data(batch, keys)
            self.assertEqual(batch.records, [])
            self.assertEqual(batch.phase, 'new')

    def test_IC07_ticket_count_or_other_session_refuses_without_preparation(self):
        batch = self.batch()
        batch.ticket._remaining = 1
        with self.assertRaises(_RequestUnavailable):
            source.prepare_inventory_guest_records_data(batch, self.keys())
        self.assertEqual(batch.records, [])
        batch.ticket._remaining = 2
        batch.ticket._session = {}
        with self.assertRaises(_RequestUnavailable):
            source.prepare_inventory_guest_records_data(batch, self.keys())
        self.assertEqual(batch.phase, 'new')

    def test_IC08_source_family_ticket_cannot_be_reused_as_guest_reservation(self):
        batch = self.batch()
        for ticket in (self.begin.family._ticket, self.begin.record._ticket):
            batch.ticket = ticket
            with self.assertRaises(_RequestUnavailable):
                source.prepare_inventory_guest_records_data(batch, self.keys())
        self.assertEqual(batch.records, [])

    def test_IC09_spent_source_stays_spent_and_private_preparation_cannot_repeat(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        retained = tuple(batch.records)
        with self.assertRaises(_RequestUnavailable):
            source.prepare_inventory_guest_records_data(batch, self.keys())
        self.assertEqual(tuple(batch.records), retained)
        self.assertTrue(self.begin.record._spent)
        self.assertEqual(len(self.fixture.owner._guest_reference_records), 1)

    def test_IC10_child_expiry_never_renews_family_or_source(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        self.assertEqual(batch.created, 111.0)
        self.assertEqual(batch.expires, 120.0)
        self.assertTrue(all(record._expires == 120.0 for record in batch.records))
        self.assertEqual(self.begin.end, 115.0)
        for created in (109.0,115.0,float('nan')):
            with self.assertRaises(_RequestUnavailable):
                source._InventoryGuestBatchData(self.begin,batch.decoded,batch.ticket,created)

    def test_IC11_equal_reconstructed_target_is_not_the_retained_guest_target(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        target = batch.records[0]._target
        batch.records[0]._target = tuple(list(target))
        self.assertEqual(batch.records[0]._target,target)
        self.assertIsNot(batch.records[0]._target,target)
        with self.assertRaises(_RequestUnavailable):
            source.prepared_inventory_guest_records_data(batch)

    def test_IC12_retire_all_known_records_after_first_genuine_control_no_refund(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        control, original = KeyboardInterrupt('fixture control'), _GuestReferenceRecord._retire
        seen = []
        def retire(record):
            seen.append(record)
            if record is batch.records[0]: raise control
            return original(record)
        with patch.object(_GuestReferenceRecord, '_retire', retire):
            error = source.retire_inventory_guest_records_data(batch, None)
        self.assertIs(error,control)
        self.assertEqual(seen,batch.records)
        self.assertTrue(batch.records[1]._retired)
        self.assertEqual(batch.ticket._state,'reserved')
        self.assertEqual(batch.ticket._remaining,2)

    def test_IC13_seeded_partial_DATA_list_retired_without_claiming_whole_result(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        batch.phase = 'prepare-attempted'
        batch.records.pop()  # Seeded partial DATA, not an actual lost return.
        self.assertIsNone(source.retire_inventory_guest_records_data(batch, None))
        self.assertTrue(batch.records[0]._retired)
        with self.assertRaises(_RequestUnavailable):
            source.prepared_inventory_guest_records_data(batch)
        self.assertEqual(batch.ticket._remaining,2)

    def test_IC14_known_record_retirement_ignores_own_quarantine_capacity_flag(self):
        batch = self.batch()
        source.prepare_inventory_guest_records_data(batch, self.keys())
        self.fixture.owner._guest_capacity._uncertain = True
        self.assertIsNone(source.retire_inventory_guest_records_data(batch, None))
        self.assertTrue(all(record._retired for record in batch.records))
        self.assertTrue(self.fixture.owner._guest_capacity._uncertain)
        self.assertEqual(batch.ticket._state,'reserved')
