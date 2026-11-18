"""UNRUN profile lookup/consumption DATA, no original body/session/gates."""
import unittest

from test_guest_inventory_children_data import InventoryChildrenData
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_profile_begin as source


class ProfileBeginData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildrenData()
        self.fixture.setUp()
        self.batch = self.fixture.batch(2)
        children.prepare_inventory_guest_records_data(self.batch,self.fixture.keys(2))
        self.f = self.fixture.fixture
        self.f.owner._guest_capacity._commit(self.batch.ticket)
        for record in self.batch.records:
            self.f.owner._guest_reference_records[
                (id(record._session),'guest',record._key)] = record
        self.record = self.batch.records[0]

    def lookup(self, now=112.0):
        return source._profile_guest_data_locked(self.f.owner,self.f.family,
            self.f.session,self.f.values[0],self.record._key,
            self.f.cohort,self.f.generation,now)

    def test_PB01_two_guests_one_configured_source_select_same_guest_target_DATA(self):
        self.assertEqual(len(self.f.cohort.nodes),1)
        self.assertEqual(self.record._ticket._remaining,2)
        before = dict(self.f.owner._guest_reference_records)
        self.assertIs(self.lookup(),self.record)
        self.assertIs(self.lookup()._target,self.batch.decoded.targets[0])
        self.assertEqual(self.f.owner._guest_reference_records,before)
        self.assertFalse(self.record._spent)

    def test_PB02_equal_foreign_session_cannot_select_or_consume(self):
        with self.assertRaises(_RequestUnavailable):
            source._profile_guest_data_locked(self.f.owner,self.f.family,{},
                self.f.values[0],self.record._key,self.f.cohort,self.f.generation,112.0)
        self.assertFalse(self.record._spent)

    def test_PB03_source_purpose_key_has_no_guest_lookup_fallback(self):
        with self.assertRaises(_RequestUnavailable):
            source._profile_guest_data_locked(self.f.owner,self.f.family,
                self.f.session,self.f.values[0],self.f.record._key,
                self.f.cohort,self.f.generation,112.0)
        self.assertFalse(self.record._spent)

    def test_PB04_other_valid_family_cannot_consume_selected_guest(self):
        ticket = self.f.owner._guest_capacity._reserve(self.f.session,self.f.values[0],1)
        family = _GuestFamilyRecord(self.f.session,self.f.values[0],'d'*64,
            self.f.cohort,self.f.generation,object(),90.0,120.0,ticket)
        self.f.owner._guest_capacity._commit(ticket)
        family._bind_once('e'*64)
        family._sources_spent = True
        with self.assertRaises(_RequestUnavailable):
            source._profile_guest_data_locked(self.f.owner,family,self.f.session,
                self.f.values[0],self.record._key,self.f.cohort,self.f.generation,112.0)
        self.assertFalse(self.record._spent)

    def test_PB05_all_malformed_target_shapes_refuse_without_consumption(self):
        for target in (None,'n',('n','qemu'),('n','qemu',100,1),
                ('/','qemu',100),('n','QEMU',100),('n','qemu',True),
                ('n','qemu',99),('n','lxc',1000000000)):
            self.record._target = target
            with self.assertRaises(source._CorruptProfileSource): self.lookup()
            self.assertFalse(self.record._spent)

    def test_PB06_equal_reconstructed_source_row_is_not_configured_membership(self):
        self.record._source = tuple(list(self.record._source))
        self.assertEqual(self.record._source,self.f.row)
        self.assertIsNot(self.record._source,self.f.row)
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.assertFalse(self.record._spent)

    def test_PB07_missing_same_ticket_membership_refuses_without_adoption(self):
        del self.f.owner._guest_capacity._tickets[id(self.batch.ticket)]
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.assertFalse(self.record._spent)
        self.assertEqual(self.batch.ticket._state,'committed')

    def test_PB08_reserved_guest_ticket_cannot_masquerade_as_issued(self):
        self.batch.ticket._state = 'reserved'
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.assertFalse(self.record._spent)
        self.assertEqual(self.batch.ticket._state,'reserved')

    def test_PB09_consume_once_keeps_charge_and_other_guest_unspent(self):
        record = self.lookup()
        before = self.f.owner._guest_capacity._check()[0]
        source._consume_profile_guest_data(record,112.0)
        self.assertTrue(record._spent)
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(record,112.1)
        self.assertEqual(self.f.owner._guest_capacity._check()[0],before)
        self.assertFalse(self.batch.records[1]._spent)
        self.assertEqual(len(self.f.owner._guest_reference_records),3)

    def test_PB10_exact_expiry_spends_and_retires_without_revival(self):
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(self.record,self.record._expires)
        self.assertTrue(self.record._spent)
        self.assertTrue(self.record._retired)
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(self.record,112.0)
        self.assertEqual(self.batch.ticket._remaining,2)

    def test_PB11_backward_clock_spends_and_retires_guest(self):
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(self.record,110.0)
        self.assertTrue(self.record._spent)
        self.assertTrue(self.record._retired)
        self.assertEqual(self.record._last_clock,111.0)

    def test_PB12_nonfinite_clock_spends_without_capacity_refund(self):
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(self.record,float('nan'))
        self.assertTrue(self.record._spent)
        self.assertTrue(self.record._retired)
        self.assertIs(self.f.owner._guest_capacity._tickets[id(self.batch.ticket)],
            self.batch.ticket)

    def test_PB13_pure_holder_captures_first_write_end_without_acquisition(self):
        original = _OriginalRequest(object(),130.0,'192.0.2.2')
        original.write_end = 114.0
        duty = source._GuestProfileBeginDuty(original,'fixture-token',self.f.session,
            self.f.values,'b'*64,self.record._key)
        self.assertIs(duty.original,original)
        self.assertEqual(duty.end,114.0)
        self.assertEqual(duty.initial_write_end,114.0)
        self.assertIsNone(duty.target)
        self.assertIsNone(duty.created)
        self.assertFalse(self.record._spent)

    def test_PB14_foreign_store_refuses_before_handler_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign handler hook')
        with self.assertRaises(_RequestUnavailable): source.begin_profile(object(),Trap())

    def test_PB15_source_record_cannot_be_consumed_by_guest_only_helper(self):
        before = (self.f.record._spent,self.f.record._retired,self.f.record._last_clock)
        with self.assertRaises(_RequestUnavailable):
            source._consume_profile_guest_data(self.f.record,112.0)
        self.assertEqual((self.f.record._spent,self.f.record._retired,
            self.f.record._last_clock),before)

    def test_PB16_changed_record_cohort_or_generation_refuses(self):
        self.record._generation = 'foreign-generation'
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.record._generation = self.f.generation
        self.record._cohort = object()
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.assertFalse(self.record._spent)

    def test_PB17_spent_guest_lookup_refuses_without_refund_or_touch(self):
        source._consume_profile_guest_data(self.record,112.0)
        before = (self.record._last_clock,self.batch.ticket._remaining)
        with self.assertRaises(_RequestUnavailable): self.lookup(112.1)
        self.assertEqual((self.record._last_clock,self.batch.ticket._remaining),before)

    def test_PB18_selected_None_row_is_corrupt_not_missing(self):
        key = (id(self.f.session),'guest',self.record._key)
        self.f.owner._guest_reference_records[key] = None
        with self.assertRaises(source._CorruptProfileSource): self.lookup()
        self.assertIn(key,self.f.owner._guest_reference_records)
        self.assertIsNone(self.f.owner._guest_reference_records[key])
        self.assertFalse(self.record._spent)
