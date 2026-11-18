"""UNRUN purpose/identity/once-consumption DATA fixture intentions only.

Fictional holders never construct successful original auth/native/handler
owners. No inventory exchange, credential/trust acquisition, child issuance,
frame, writer/current recipient or physical cleanup behavior is exercised.
"""
from types import SimpleNamespace
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_begin as source


class InventoryBeginData(unittest.TestCase):
    def setUp(self):
        self.session, self.generation = {}, 'fixture-generation'
        self.principal = 'fixture-user'
        self.row = ('fixture-label', TargetSnapshot(self.generation,
            'fixture-node', '192.0.2.1'))
        self.cohort = SimpleNamespace(nodes=(self.row,))
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_reference_records={})
        capacity = self.owner._guest_capacity
        family_ticket = capacity._reserve(self.session, self.principal, 1)
        self.family = _GuestFamilyRecord(self.session, self.principal, 'a'*64,
            self.cohort, self.generation, object(), 90.0, 120.0, family_ticket)
        capacity._commit(family_ticket)
        self.family._bind_once('b'*64)
        self.family._sources_spent = True
        self.ticket = capacity._reserve(self.session, self.principal, 1)
        self.record = _GuestReferenceRecord('c'*64, 'source', self.session,
            self.principal, self.row, self.generation, self.cohort, None,
            100.0, 120.0, self.ticket, self.family)
        capacity._commit(self.ticket)
        self.key = (id(self.session), 'source', 'c'*64)
        self.owner._guest_reference_records[self.key] = self.record

    def lookup(self, session=None, reference='c'*64, now=110.0):
        return source._inventory_source_data_locked(self.owner, self.family,
            self.session if session is None else session, self.principal,
            reference, self.cohort, self.generation, now)

    def test_IB01_lookup_preserves_exact_original_row_and_charge_DATA(self):
        self.assertIs(self.lookup(), self.record)
        self.assertIs(self.record._source, self.row)
        self.assertFalse(self.record._spent)
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)

    def test_IB02_foreign_equal_session_cannot_select_or_consume(self):
        with self.assertRaises(_RequestUnavailable): self.lookup(session={})
        self.assertFalse(self.record._spent)

    def test_IB03_guest_purpose_and_missing_source_never_fall_back(self):
        del self.owner._guest_reference_records[self.key]
        self.owner._guest_reference_records[(id(self.session),'guest','c'*64)] = self.record
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertFalse(self.record._spent)
        with self.assertRaises(_RequestUnavailable): self.lookup(reference='d'*64)

    def test_IB04_present_None_row_is_corrupt_not_missing(self):
        self.owner._guest_reference_records[self.key] = None
        with self.assertRaises(source._CorruptInventorySource): self.lookup()

    def test_IB05_other_valid_family_cannot_consume_selected_row(self):
        capacity = self.owner._guest_capacity
        ticket = capacity._reserve(self.session, self.principal, 1)
        other = _GuestFamilyRecord(self.session, self.principal, 'd'*64,
            self.cohort, self.generation, object(), 90.0, 120.0, ticket)
        capacity._commit(ticket)
        other._bind_once('e'*64)
        self.record._family = other
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertFalse(self.record._spent)
        self.assertFalse(self.record._retired)

    def test_IB06_equal_reconstructed_source_row_is_not_original_membership(self):
        self.record._source = (self.row[0], self.row[1])
        self.assertEqual(self.record._source, self.row)
        self.assertIsNot(self.record._source, self.row)
        with self.assertRaises(source._CorruptInventorySource): self.lookup()

    def test_IB07_changed_cohort_generation_ticket_or_purpose_refuse(self):
        for field,value in (('_cohort',object()),('_generation',object()),
                            ('_ticket',object()),('_purpose','guest'),('_family',None)):
            old = getattr(self.record, field)
            setattr(self.record, field, value)
            with self.assertRaises(source._CorruptInventorySource): self.lookup()
            setattr(self.record, field, old)
        self.assertFalse(self.record._spent)

    def test_IB08_missing_or_reserved_or_oversized_ticket_is_corrupt(self):
        capacity = self.owner._guest_capacity
        del capacity._tickets[id(self.ticket)]
        with self.assertRaises(source._CorruptInventorySource): self.lookup()
        capacity._tickets[id(self.ticket)] = self.ticket
        self.ticket._state = 'reserved'
        with self.assertRaises(source._CorruptInventorySource): self.lookup()
        self.ticket._state = 'committed'
        self.ticket._remaining = 2
        with self.assertRaises(source._CorruptInventorySource): self.lookup()

    def test_IB09_source_spends_once_without_capacity_refund_or_new_ticket(self):
        record = self.lookup()
        before = dict(self.owner._guest_capacity._tickets)
        source._consume_inventory_source_data(record, 110.0)
        self.assertTrue(record._spent)
        self.assertFalse(record._retired)
        self.assertEqual(self.owner._guest_capacity._tickets, before)
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)
        with self.assertRaises(_RequestUnavailable): self.lookup()
        with self.assertRaises(_RequestUnavailable): source._consume_inventory_source_data(record, 110.0)

    def test_IB10_expired_source_spent_and_retired_cannot_revive_on_old_clock(self):
        source_record = self.lookup(now=120.0)
        with self.assertRaises(_RequestUnavailable):
            source._consume_inventory_source_data(source_record, 120.0)
        self.assertTrue(source_record._spent)
        self.assertTrue(source_record._retired)
        with self.assertRaises(_RequestUnavailable): self.lookup(now=110.0)
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)

    def test_IB11_backward_record_clock_spends_and_retires_before_refusal(self):
        record = self.lookup(now=99.0)
        with self.assertRaises(_RequestUnavailable):
            source._consume_inventory_source_data(record, 99.0)
        self.assertTrue(record._spent)
        self.assertTrue(record._retired)
        self.assertEqual(record._last_clock, 100.0)
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)

    def test_IB12_wrong_64hex_or_nonfinite_clock_cannot_select(self):
        for reference in ('c'*32,'C'*64,'c'*63,'c'*65):
            with self.assertRaises(_RequestUnavailable): self.lookup(reference=reference)
        for now in (110,True,float('nan'),float('inf')):
            with self.assertRaises(_RequestUnavailable): self.lookup(now=now)
        self.assertFalse(self.record._spent)

    def test_IB13_unspent_or_retired_family_refuses_before_child_consumption(self):
        self.family._sources_spent = False
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.family._sources_spent = True
        self.family._retire()
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertFalse(self.record._spent)

    def test_IB14_holder_retains_earlier_write_end_without_acquisition(self):
        original = SimpleNamespace(end=130.0,write_end=115.0)
        d = source._GuestInventoryBeginDuty(original,'fixture-token',self.session,
            ('fixture-user','viewer',1.0,1.0,'fixture-csrf'),'b'*64,'c'*64)
        self.assertIs(d.original, original)
        self.assertIs(d.session, self.session)
        self.assertEqual(d.end, 115.0)
        self.assertEqual(d.initial_write_end, 115.0)
        self.assertIsNone(d.record)
        self.assertFalse(hasattr(d,'acquire'))
        self.assertFalse(hasattr(d,'run'))

    def test_IB15_foreign_store_refuses_before_handler_hooks(self):
        class HandlerTrap:
            def __getattribute__(self, name):
                raise AssertionError('supplied handler hook reached')
        with self.assertRaises(_RequestUnavailable):
            source.begin_inventory(object(),HandlerTrap())
