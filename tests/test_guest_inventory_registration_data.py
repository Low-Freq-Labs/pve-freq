"""UNRUN consumed-source and bounded registration DATA intentions only.

Fictional original-request storage and placeholder locks/server do not create
an actual native original owner, session, allowance, writer or cleanup proof.
No positive original registration function or acquisition is exercised.
"""
from types import SimpleNamespace
from freq.api import auth
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable, _OriginalRequest
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_inventory_begin import (
    _GuestInventoryBeginDuty, _CorruptInventorySource,
)
from freq.services.pilot_guest_inventory_consumed import consumed_inventory_source_data_locked
from freq.services import pilot_guest_inventory_registration as source


class InventoryRegistrationData(unittest.TestCase):
    def setUp(self):
        self.session,self.generation = {},'fixture-generation'
        self.values=('fixture-user','viewer',1.0,1.0,'fixture-csrf')
        self.row=('fixture-label',TargetSnapshot(self.generation,'fixture-node','192.0.2.1'))
        self.token=('fixture@pam','fixture-configured-name')
        self.cohort=SimpleNamespace(nodes=(self.row,),token_id=self.token)
        self.owner=SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_reference_records={},_gate=object(),_server=object())
        capacity=self.owner._guest_capacity
        ticket=capacity._reserve(self.session,self.values[0],1)
        self.family=_GuestFamilyRecord(self.session,self.values[0],'a'*64,
            self.cohort,self.generation,object(),90.0,120.0,ticket)
        capacity._commit(ticket);self.family._bind_once('b'*64)
        self.family._sources_spent=True
        ticket=capacity._reserve(self.session,self.values[0],1)
        self.record=_GuestReferenceRecord('c'*64,'source',self.session,self.values[0],
            self.row,self.generation,self.cohort,None,100.0,120.0,ticket,self.family)
        capacity._commit(ticket);self.record._consume_once(110.0)
        self.owner._guest_reference_records[(id(self.session),'source','c'*64)]=self.record
        self.owner._original_component_tables=({},{},{},{},{},{},{},
            self.owner._guest_reference_records,capacity._tickets)
        self.owner._guest_inventory_attempts={}
        self.owner._native_guest_inventory_attempts={}
        self.owner._original_guest_inventory_tables=(self.owner._guest_inventory_attempts,
            self.owner._native_guest_inventory_attempts)
        self.store=SimpleNamespace(_installation=self.owner,
            _broker=SimpleNamespace(_requests={},_gate=object()),
            _references=SimpleNamespace(_lock=object()),
            _auth=SimpleNamespace())

    def lookup(self,now=111.0):
        return consumed_inventory_source_data_locked(self.owner,self.family,
            self.session,self.values[0],'c'*64,self.cohort,self.generation,now)

    def duty(self):
        original=_OriginalRequest(object(),115.0,'192.0.2.2')
        begin=_GuestInventoryBeginDuty(original,'fixture-token',self.session,
            self.values,'b'*64,'c'*64)
        begin.family,begin.record,begin.source=self.family,self.record,self.row
        begin.cohort,begin.generation=self.cohort,self.generation
        begin.phase='registration-attempted'
        d=source._InventoryAcquisitionDuty(original,begin)
        d.credential_uid,d.configured_token=2001,self.token
        d.component_tables=self.owner._original_component_tables
        d.inventory_tables=self.owner._original_guest_inventory_tables
        d.custody=source._InventoryRetirementCustody(self.store,original,object(),d)
        d.phase='captured'
        return d

    def test_IR01_consumed_lookup_does_not_consume_or_update_clock_again(self):
        before=(self.record._spent,self.record._retired,self.record._last_clock,
            self.owner._guest_capacity._check()[0])
        self.assertIs(self.lookup(),self.record)
        self.assertEqual((self.record._spent,self.record._retired,self.record._last_clock,
            self.owner._guest_capacity._check()[0]),before)

    def test_IR02_unspent_or_retired_source_is_not_continuation(self):
        self.record._spent=False
        with self.assertRaises(_RequestUnavailable):self.lookup()
        self.assertFalse(self.record._spent)
        self.record._spent=True;self.record._retired=True
        with self.assertRaises(_RequestUnavailable):self.lookup()

    def test_IR03_stale_and_backward_time_refuse_without_mutation(self):
        for now in (109.0,120.0,121.0):
            with self.assertRaises(_RequestUnavailable):self.lookup(now)
        self.assertTrue(self.record._spent)
        self.assertFalse(self.record._retired)
        self.assertEqual(self.record._last_clock,110.0)
        self.assertEqual(self.owner._guest_capacity._check()[0],2)

    def test_IR04_corrupt_selected_row_and_equal_foreign_source_refuse(self):
        rows=self.owner._guest_reference_records
        key=(id(self.session),'source','c'*64)
        rows[key]=None
        with self.assertRaises(_CorruptInventorySource):self.lookup()
        rows[key]=self.record;self.record._source=(self.row[0],self.row[1])
        self.assertIsNot(self.record._source,self.row)
        with self.assertRaises(_CorruptInventorySource):self.lookup()

    def test_IR05_placeholder_and_snapshot_do_not_acquire_or_authorize(self):
        d=self.duty()
        self.assertIsNone(d.slot.attempt)
        self.assertEqual(d.slot.phase,'uninitialized')
        self.assertFalse(hasattr(d.slot,'run'))
        self.assertFalse(hasattr(d,'acquire'))
        self.assertEqual(d.charge,15442019)
        self.assertEqual(d.end,115.0)
        self.assertEqual(len(d.custody.items),29)
        self.assertIs(d.custody.items[14],d)
        self.assertIs(d.custody.items[24],d.slot)

    def test_IR06_custody_pointer_tuple_is_immutable_DATA(self):
        d=self.duty();saved=d.custody.items
        with self.assertRaises(TypeError):d.custody.items=()
        with self.assertRaises(TypeError):del d.custody.items
        self.assertIs(d.custody.items,saved)

    def test_IR07_logical_and_native_registration_retain_same_unstarted_duty(self):
        d=self.duty()
        self.assertTrue(source._register_inventory_duty_data(self.owner,d))
        self.assertIs(self.owner._native_guest_inventory_attempts[d.original],d)
        self.assertIs(self.owner._guest_inventory_attempts[d.original],d)
        self.assertEqual(d.phase,'registered')
        self.assertIsNone(d.slot.attempt)
        self.assertEqual(self.owner._guest_capacity._check()[0],2)

    def test_IR08_same_registration_cannot_repeat_or_refund(self):
        d=self.duty();source._register_inventory_duty_data(self.owner,d)
        with self.assertRaises(_CorruptInventorySource):
            source._register_inventory_duty_data(self.owner,d)
        self.assertEqual(len(self.owner._native_guest_inventory_attempts),1)
        self.assertIs(self.owner._native_guest_inventory_attempts[d.original],d)

    def test_IR09_sixtyfour_typed_DATA_entries_refuse_sixtyfifth_without_clear(self):
        # Same fictional source reused only as count DATA, never native rights.
        for _ in range(64):
            self.assertTrue(source._register_inventory_duty_data(self.owner,self.duty()))
        d=self.duty()
        self.assertFalse(source._register_inventory_duty_data(self.owner,d))
        self.assertEqual(d.phase,'captured')
        self.assertNotIn(d.original,self.owner._native_guest_inventory_attempts)
        self.assertEqual(len(self.owner._native_guest_inventory_attempts),64)
        self.assertEqual(len(self.owner._guest_inventory_attempts),64)
        self.assertEqual(self.owner._guest_capacity._check()[0],2)

    def test_IR10_unknown_prior_registration_DATA_refuses_and_retains_it(self):
        old=self.duty();source._register_inventory_duty_data(self.owner,old)
        old.phase='registration-pending'  # Fictional uncertainty state, not injected return loss.
        del self.owner._guest_inventory_attempts[old.original]
        with self.assertRaises(_CorruptInventorySource):
            source._register_inventory_duty_data(self.owner,self.duty())
        self.assertIs(self.owner._native_guest_inventory_attempts[old.original],old)
        self.assertEqual(old.phase,'registration-pending')

    def test_IR11_wrong_charge_or_slot_shape_refuses_without_new_entry(self):
        for field,value in (('charge',True),('charge',15442020),('slot',object())):
            d=self.duty();setattr(d,field,value)
            with self.assertRaises(_CorruptInventorySource):
                source._register_inventory_duty_data(self.owner,d)
            self.assertEqual(self.owner._native_guest_inventory_attempts,{})

    def test_IR12_replaced_tables_refuse_without_clearing_originals(self):
        d=self.duty();original=d.inventory_tables
        self.owner._guest_inventory_attempts={}
        with self.assertRaises(_CorruptInventorySource):
            source._register_inventory_duty_data(self.owner,d)
        self.assertEqual(original,({},{}))
        self.assertIs(self.owner._original_guest_inventory_tables,original)

    def test_IR13_foreign_store_refuses_before_handler_hooks(self):
        class HandlerTrap:
            def __getattribute__(self,name):raise AssertionError('foreign handler hook reached')
        with self.assertRaises(_RequestUnavailable):
            source.register_inventory_acquisition(object(),HandlerTrap())

    def test_IR14_foreign_duty_refuses_before_its_attribute_hooks(self):
        class DutyTrap:
            def __getattribute__(self,name):raise AssertionError('foreign duty hook reached')
        with self.assertRaises(_CorruptInventorySource):
            source._inventory_registration_tables_data(self.owner,DutyTrap())

    def test_IR15_snapshot_uses_canonical_auth_module_lock_without_owner_fallback(self):
        # Pure snapshot DATA only: this fake auth transaction intentionally
        # lacks the nonexistent field which masked R1 correspondence F01.
        self.assertFalse(hasattr(self.store._auth, '_auth_lock'))
        d = self.duty()
        self.assertIs(d.custody.items[13][1], auth._auth_lock)
        neighbor = object()
        self.store._auth._auth_lock = neighbor
        other = self.duty()
        self.assertIs(other.custody.items[13][1], auth._auth_lock)
        self.assertIsNot(other.custody.items[13][1], neighbor)
