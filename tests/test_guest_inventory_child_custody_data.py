"""UNRUN fixed child slot/29pointer custody DATA, no actual original writer."""
import unittest
from unittest.mock import patch

from test_guest_inventory_child_reservation_data import InventoryChildReservationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_registration as registration
from freq.services import pilot_guest_inventory_child_reservation_data as counter
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_retirement as retirement


class InventoryChildCustodyData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildReservationData()
        self.fixture.setUp()
        self.f = self.fixture.fixture
        self.acquisition = self.fixture.acquisition

    def retained(self, count=2):
        return self.fixture.duty(count)

    def test_CC01_child_slot_is_captured_at29th_position_before_counter_effects(self):
        acquisition = self.acquisition
        self.assertIsInstance(acquisition.children,registration._InventoryChildSlot)
        self.assertEqual(acquisition.children.phase,'uninitialized')
        self.assertIsNone(acquisition.children.reservation)
        self.assertEqual(len(acquisition.custody.items),29)
        self.assertIs(acquisition.custody.items[28],acquisition.children)
        self.assertEqual(self.f.owner._guest_capacity._check()[0],2)

    def test_CC02_retention_stores_same_counter_before_reserve_and_cannot_repeat(self):
        duty = self.retained()
        slot = self.acquisition.children
        self.assertIs(slot.reservation,duty)
        self.assertEqual(slot.phase,'retained')
        self.assertIsNone(duty.ticket)
        self.assertEqual(duty.capacity._check()[0],2)
        with self.assertRaises(_RequestUnavailable):
            counter.retain_inventory_child_reservation_data(
                self.f.owner,self.acquisition,duty.decoded,111.0)
        self.assertIs(slot.reservation,duty)
        self.assertEqual(duty.capacity._check()[0],2)

    def test_CC03_equal_reconstructed_counter_cannot_reserve_or_retire_real_slot(self):
        duty = self.retained()
        other = counter._InventoryChildReservationData(
            self.f.owner,self.acquisition,duty.decoded,111.0)
        with self.assertRaises(_RequestUnavailable): counter.reserve_inventory_children_data(other)
        self.assertIsInstance(counter.retire_inventory_child_reservation_data(other,None),
            _RequestUnavailable)
        self.assertIs(self.acquisition.children.reservation,duty)
        self.assertIsNone(duty.ticket)
        self.assertEqual(duty.capacity._check()[0],2)

    def test_CC04_source_then_known_child_counter_settles_no_native_charge_refund(self):
        duty = self.retained()
        counter.reserve_inventory_children_data(duty)
        self.assertIsNone(retirement._retire_unstarted_holders_data(self.acquisition,None))
        self.assertTrue(self.f.record._retired)
        self.assertEqual(duty.phase,'retired')
        self.assertEqual(self.acquisition.children.phase,'retired')
        self.assertIs(self.acquisition.children.reservation,duty)
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertIs(self.f.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)
        self.assertEqual(self.acquisition.charge,15442019)

    def test_CC05_source_control_does_not_skip_known_child_counter_cleanup(self):
        duty = self.retained()
        counter.reserve_inventory_children_data(duty)
        control = KeyboardInterrupt('fixture source terminal control')
        with patch.object(_GuestReferenceRecord,'_retire',side_effect=control):
            error = retirement._retire_unstarted_holders_data(self.acquisition,None)
        self.assertIs(error,control)
        self.assertEqual(duty.phase,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertIs(self.acquisition.children.reservation,duty)

    def test_CC06_unknown_native_slot_does_not_skip_known_child_cleanup_or_call_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('native hook reached')
        duty = self.retained()
        counter.reserve_inventory_children_data(duty)
        held = Trap()
        self.acquisition.slot.attempt = held
        error = retirement._retire_unstarted_holders_data(self.acquisition,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertIs(self.acquisition.slot.attempt,held)
        self.assertEqual(duty.phase,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)

    def test_CC07_child_control_tries_later_record_without_ticket_refund(self):
        duty = self.retained()
        counter.reserve_inventory_children_data(duty)
        children.prepare_inventory_guest_records_data(duty.batch,('1'*64,'2'*64))
        original, control, seen = _GuestReferenceRecord._retire, KeyboardInterrupt('fixture child control'), []
        def retire(record):
            seen.append(record)
            if record is duty.batch.records[0]: raise control
            original(record)
        with patch.object(_GuestReferenceRecord,'_retire',retire):
            error = retirement._retire_unstarted_holders_data(self.acquisition,None)
        self.assertIs(error,control)
        self.assertEqual(seen,[self.f.record]+duty.batch.records)
        self.assertTrue(duty.batch.records[1]._retired)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertEqual(self.acquisition.children.phase,'retained')

    def test_CC08_replaced_child_slot_refuses_and_retains_original_captured_duty(self):
        duty = self.retained()
        counter.reserve_inventory_children_data(duty)
        saved = self.acquisition.children
        self.acquisition.children = registration._InventoryChildSlot()
        error = retirement._retire_unstarted_holders_data(self.acquisition,None)
        self.assertIsInstance(error,_RequestUnavailable)
        self.assertIs(self.acquisition.custody.items[28],saved)
        self.assertIs(saved.reservation,duty)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertFalse(self.f.record._retired)

    def test_CC09_unknown_child_constructor_return_keeps_pending_no_retry(self):
        # Obtain decoded DATA without retaining on this acquisition.
        decoded = children._DecodedGuestRowsData(b'{"data":[]}')
        control = KeyboardInterrupt('fixture lost pure counter constructor')
        with patch.object(counter,'_InventoryChildReservationData',side_effect=control):
            with self.assertRaises(KeyboardInterrupt) as caught:
                counter.retain_inventory_child_reservation_data(
                    self.f.owner,self.acquisition,decoded,111.0)
        self.assertIs(caught.exception,control)
        self.assertEqual(self.acquisition.children.phase,'retention-attempted')
        self.assertIsNone(self.acquisition.children.reservation)
        with self.assertRaises(_RequestUnavailable):
            counter.retain_inventory_child_reservation_data(
                self.f.owner,self.acquisition,decoded,111.0)
        self.assertIsInstance(retirement._retire_unstarted_holders_data(self.acquisition,None),
            _RequestUnavailable)
        self.assertEqual(self.f.owner._guest_capacity._check()[0],2)

    def test_CC10_lost_reserve_return_preserves_same_child_slot_and_unknown_ticket_charge(self):
        duty = self.retained()
        original = _GuestCapacity._reserve
        def reserve(capacity,*args):
            original(capacity,*args)
            raise RuntimeError('fixture lost counter return')
        with patch.object(_GuestCapacity,'_reserve',reserve):
            with self.assertRaises(RuntimeError): counter.reserve_inventory_children_data(duty)
        saved = dict(duty.ledger)
        self.assertIsInstance(retirement._retire_unstarted_holders_data(self.acquisition,None),
            _RequestUnavailable)
        self.assertEqual(duty.ledger,saved)
        self.assertIs(self.acquisition.children.reservation,duty)
        self.assertIsNone(duty.ticket)
        self.assertEqual(duty.phase,'reserve-attempted')
        self.assertTrue(duty.capacity._uncertain)

    def test_CC11_repeat_known_child_cleanup_preserves_same_native_tombstone(self):
        duty = self.retained(0)
        counter.reserve_inventory_children_data(duty)
        for _ in range(2):
            self.assertIsNone(retirement._retire_unstarted_holders_data(self.acquisition,None))
        self.assertEqual(self.acquisition.children.phase,'retired')
        self.assertIs(self.acquisition.children.reservation,duty)
        self.assertIs(self.f.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)

    def test_CC12_foreign_child_slot_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('child slot hook reached')
        saved = self.acquisition.children
        self.acquisition.children = Trap()
        self.assertIsInstance(retirement._retire_unstarted_holders_data(self.acquisition,None),
            _RequestUnavailable)
        self.assertIs(self.acquisition.custody.items[28],saved)

    def test_CC13_native_table_DATA_filter_accepts_fixed_retained_child_only(self):
        duty = self.retained()
        active, native = registration._inventory_registration_tables_data(
            self.f.owner,self.acquisition)
        self.assertIs(active[self.acquisition.original],self.acquisition)
        self.assertIs(native[self.acquisition.original],self.acquisition)
        duty.owner = object()
        with self.assertRaises(registration._CorruptInventorySource):
            registration._inventory_registration_tables_data(self.f.owner,self.acquisition)
        self.assertIs(self.acquisition.children.reservation,duty)

    def test_CC14_pending_child_shape_refuses_new_registration_without_clearing_native(self):
        self.acquisition.children.phase = 'retention-attempted'
        with self.assertRaises(registration._CorruptInventorySource):
            registration._inventory_registration_tables_data(self.f.owner,self.acquisition)
        self.assertIs(self.f.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)
        self.assertIsNone(self.acquisition.children.reservation)
