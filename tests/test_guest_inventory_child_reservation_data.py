"""UNRUN counter DATA only; no original child writer or native result receipt."""
import json
import unittest
from unittest.mock import patch

from test_guest_inventory_registration_data import InventoryRegistrationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_registration as registration
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_child_reservation_data as source


class InventoryChildReservationData(unittest.TestCase):
    def setUp(self):
        f = self.fixture = InventoryRegistrationData()
        f.setUp()
        self.acquisition = f.duty()
        self.acquisition.last_clock = 110.0
        registration._register_inventory_duty_data(f.owner, self.acquisition)
        # Existing canonical owner fields, fictional objects only in this test.
        f.owner._original_guest_capacity = f.owner._guest_capacity
        tables = f.owner._original_component_tables
        for field, value in zip(('_auth_attempts','_asset_attempts','_issued_sessions',
                '_read_attempts','_native_read_attempts','_guest_families_by_nonce',
                '_guest_families_by_ref','_guest_reference_records'), tables[:8]):
            setattr(f.owner,field,value)

    def duty(self, count=2):
        raw = json.dumps({'data':[dict(type='qemu',node='n',vmid=100+i)
            for i in range(count)]},separators=(',',':')).encode('utf-8')
        decoded = children._DecodedGuestRowsData(raw)
        source.retain_inventory_child_reservation_data(
            self.fixture.owner,self.acquisition,decoded,111.0)
        return self.acquisition.children.reservation

    def test_CR01_whole_ticket_retained_before_empty_private_batch(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.phase,'batch-retained')
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertIs(duty.batch.ticket,duty.ticket)
        self.assertEqual(duty.ticket._remaining,2)
        self.assertEqual(duty.batch.records,[])
        self.assertIsNone(duty.batch.candidates)
        self.assertEqual(duty.capacity._check()[0],4)
        self.assertTrue(self.fixture.record._spent)
        self.assertEqual(len(self.fixture.owner._guest_reference_records),1)

    def test_CR02_zero_ticket_known_cleanup_settles_only_logical_counter(self):
        duty = self.duty(0)
        source.reserve_inventory_children_data(duty)
        ticket = duty.ticket
        self.assertEqual(ticket._state,'reserved')
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        self.assertEqual(ticket._state,'retired')
        self.assertNotIn(id(ticket),duty.ledger)
        self.assertEqual(duty.capacity._check()[0],2)
        self.assertIs(self.fixture.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)
        self.assertEqual(self.acquisition.charge,15442019)

    def test_CR03_known_session_full_refuses_without_uncertainty_or_new_ticket(self):
        duty = self.duty(1)
        f = self.fixture
        for _ in range(2): duty.capacity._reserve(f.session,f.values[0],255)
        before = dict(duty.ledger)
        source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.phase,'refused')
        self.assertIsNone(duty.ticket)
        self.assertEqual(duty.ledger,before)
        self.assertFalse(duty.capacity._uncertain)
        self.assertTrue(f.record._spent)
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        self.assertEqual(duty.ledger,before)

    def test_CR04_known_owner4096_full_refuses_whole_inventory(self):
        duty = self.duty(1)
        for _ in range(15): duty.capacity._reserve({},'other-fixture',256)
        duty.capacity._reserve({},'last-fixture',254)
        self.assertEqual(duty.capacity._check()[0],4096)
        before = dict(duty.ledger)
        source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.phase,'refused')
        self.assertEqual(duty.ledger,before)
        self.assertFalse(duty.capacity._uncertain)

    def test_CR05_zero_count_does_not_bypass512_ticket_limit(self):
        duty = self.duty(0)
        f = self.fixture
        for _ in range(510): duty.capacity._reserve(f.session,f.values[0],0)
        source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.phase,'refused')
        self.assertIsNone(duty.ticket)
        self.assertEqual(len(duty.ledger),512)

    def test_CR06_same_retained_DATA_object_cannot_reserve_twice(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        before = dict(duty.ledger)
        with self.assertRaises(_RequestUnavailable): source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.ledger,before)
        self.assertEqual(duty.capacity._check()[0],4)

    def test_CR07_injected_lost_reserve_return_stays_charged_without_adoption(self):
        duty = self.duty()
        original = _GuestCapacity._reserve
        control = KeyboardInterrupt('fixture lost reserve return')
        before = set(duty.ledger)
        def reserve(capacity,*args):
            original(capacity,*args)
            raise control
        with patch.object(_GuestCapacity,'_reserve',reserve):
            with self.assertRaises(KeyboardInterrupt) as caught:
                source.reserve_inventory_children_data(duty)
        self.assertIs(caught.exception,control)
        self.assertEqual(duty.phase,'reserve-attempted')
        self.assertIsNone(duty.ticket)
        self.assertIsNone(duty.batch)
        self.assertTrue(duty.capacity._uncertain)
        self.assertEqual(len(set(duty.ledger)-before),1)
        after = dict(duty.ledger)
        self.assertIsInstance(source.retire_inventory_child_reservation_data(duty,None),
            _RequestUnavailable)
        self.assertEqual(duty.ledger,after)

    def test_CR08_failed_batch_allocation_keeps_known_ticket_for_cleanup_after_quarantine(self):
        duty = self.duty()
        original, calls = source._InventoryGuestBatchData, []
        def construct(*args):
            calls.append(args)
            if len(calls)==2: raise RuntimeError('fixture retained ticket before batch')
            return original(*args)
        with patch.object(source,'_InventoryGuestBatchData',construct):
            with self.assertRaises(RuntimeError): source.reserve_inventory_children_data(duty)
        self.assertEqual(duty.phase,'reserved')
        self.assertIsNone(duty.batch)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertTrue(duty.capacity._uncertain)
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertTrue(duty.capacity._uncertain)  # No repair/positive restoration.

    def test_CR09_prior_body_control_does_not_skip_known_ticket_cleanup(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        control = KeyboardInterrupt('fixture original body control')
        self.assertIs(source.retire_inventory_child_reservation_data(duty,control),control)
        self.assertEqual(duty.phase,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertEqual(duty.capacity._check()[0],2)

    def test_CR10_known_child_failure_tries_later_holder_but_never_guesses_refund(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        children.prepare_inventory_guest_records_data(duty.batch,('1'*64,'2'*64))
        control, original, seen = KeyboardInterrupt('fixture child control'), _GuestReferenceRecord._retire, []
        def retire(record):
            seen.append(record)
            if record is duty.batch.records[0]: raise control
            original(record)
        with patch.object(_GuestReferenceRecord,'_retire',retire):
            error = source.retire_inventory_child_reservation_data(duty,None)
        self.assertIs(error,control)
        self.assertEqual(seen,duty.batch.records)
        self.assertTrue(duty.batch.records[1]._retired)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertEqual(duty.ticket._state,'reserved')

    def test_CR11_indexed_selected_ticket_is_never_refunded_as_unpublished(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        children.prepare_inventory_guest_records_data(duty.batch,('1'*64,'2'*64))
        record = duty.batch.records[0]
        rows = self.fixture.owner._guest_reference_records
        key = (id(self.fixture.session),'guest',record._key)
        rows[key] = record  # Seeded corrupt publication, not a genuine issuer.
        self.assertIsInstance(source.retire_inventory_child_reservation_data(duty,None),
            _RequestUnavailable)
        self.assertIs(rows[key],record)
        self.assertIs(duty.ledger[id(duty.ticket)],duty.ticket)
        self.assertTrue(duty.capacity._uncertain)

    def test_CR12_replaced_ledger_refuses_without_repair_or_clear(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        retained = dict(duty.ledger)
        duty.capacity._tickets = {}
        self.assertIsInstance(source.retire_inventory_child_reservation_data(duty,None),
            _RequestUnavailable)
        self.assertEqual(duty.ledger,retained)
        self.assertEqual(duty.capacity._tickets,{})

    def test_CR13_known_ticket_cleanup_ignores_own_positive_lifetime_flags(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        duty.capacity._uncertain = True
        self.acquisition.phase = 'retired'
        self.fixture.record._retired = True
        self.fixture.family._retire()
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        self.assertEqual(duty.phase,'retired')
        self.assertNotIn(id(duty.ticket),duty.ledger)
        self.assertTrue(duty.capacity._uncertain)

    def test_CR14_known_retired_ticket_repeats_without_mutation_or_native_clear(self):
        duty = self.duty()
        source.reserve_inventory_children_data(duty)
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        saved = dict(duty.ledger)
        self.assertIsNone(source.retire_inventory_child_reservation_data(duty,None))
        self.assertEqual(duty.ledger,saved)
        self.assertIs(self.fixture.owner._native_guest_inventory_attempts[
            self.acquisition.original],self.acquisition)

    def test_CR15_foreign_DATA_duty_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign duty hook')
        with self.assertRaises(_RequestUnavailable): source.reserve_inventory_children_data(Trap())
        self.assertIsInstance(source.retire_inventory_child_reservation_data(Trap(),None),
            _RequestUnavailable)
