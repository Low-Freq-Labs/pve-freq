"""UNRUN pure pending-object storage intentions, no original native owner.

Canonical pending allocation/preparation is Python storage only. No server,
gate, trust, credential, socket, native attempt, final admission or physical
parent is constructed. True identity DATA filters never imply native-current.
"""
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_pilot_startup import OriginalPilotInstallation


class InventoryNativeStorageData(unittest.TestCase):
    def prepared(self):
        owner = OriginalPilotInstallation()
        owner._prepare_pending_original()
        return owner

    def test_NS01_all_new_slots_are_None_before_pure_preparation(self):
        owner = OriginalPilotInstallation()
        for name in ('_guest_inventory_attempts','_native_guest_inventory_attempts',
                     '_original_guest_inventory_tables','_gate','_server'):
            self.assertIsNone(getattr(owner,name))
        self.assertIs(owner._native_current_locked(None),False)
        self.assertIs(owner._live,False)

    def test_NS02_original_nine_maps_and_two_new_maps_are_all_distinct(self):
        owner = self.prepared()
        old = owner._original_component_tables
        new = owner._original_guest_inventory_tables
        self.assertEqual(len(old),9)
        self.assertEqual(len(new),2)
        self.assertEqual(len({id(x) for x in old+new}),11)
        self.assertTrue(all(type(x) is dict and not x for x in old+new))
        self.assertIs(new[0],owner._guest_inventory_attempts)
        self.assertIs(new[1],owner._native_guest_inventory_attempts)
        self.assertTrue(owner._original_component_tables_current())
        self.assertTrue(owner._original_guest_inventory_tables_current())
        self.assertIs(owner._native_current_locked(None),False)
        self.assertIsNone(owner._server)
        self.assertIsNone(owner._gate)

    def test_NS03_repeat_prepare_cannot_replace_original_storage(self):
        owner = self.prepared()
        old,new = owner._original_component_tables,owner._original_guest_inventory_tables
        with self.assertRaises(_RequestUnavailable):owner._prepare_pending_original()
        self.assertIs(owner._original_component_tables,old)
        self.assertIs(owner._original_guest_inventory_tables,new)
        self.assertEqual(owner._pending_state,'prepared')
        self.assertIs(owner._native_current_locked(None),False)

    def test_NS04_replacement_or_alias_refuses_without_touching_old_maps(self):
        for which in ('replace','alias-new','alias-old'):
            owner = self.prepared()
            old,new = owner._original_component_tables,owner._original_guest_inventory_tables
            if which=='replace':owner._guest_inventory_attempts={}
            elif which=='alias-new':owner._guest_inventory_attempts=new[1]
            else:owner._guest_inventory_attempts=old[3]
            self.assertFalse(owner._original_guest_inventory_tables_current())
            self.assertIs(owner._original_component_tables,old)
            self.assertTrue(owner._original_component_tables_current())
            self.assertEqual(new,({},{}))
            self.assertIs(owner._native_current_locked(None),False)

    def test_NS05_entry_64_is_only_DATA_and_65_refuses_without_clear(self):
        for field in ('_guest_inventory_attempts','_native_guest_inventory_attempts'):
            owner = self.prepared()
            table = getattr(owner,field)
            for n in range(64):table[n]=object()  # Fictional count DATA only.
            self.assertTrue(owner._original_guest_inventory_tables_current())
            self.assertIs(owner._native_current_locked(None),False)
            marker = object();table[64]=marker
            self.assertFalse(owner._original_guest_inventory_tables_current())
            self.assertEqual(len(table),65)
            self.assertIs(table[64],marker)

    def test_NS06_quarantine_filter_refusal_retains_native_DATA_duty(self):
        owner = self.prepared()
        native = owner._native_guest_inventory_attempts
        marker = object();native['fictional-original-request']=marker
        original_tuple = owner._original_guest_inventory_tables
        owner._guest_capacity._uncertain=True
        self.assertFalse(owner._original_guest_inventory_tables_current())
        self.assertIs(owner._original_guest_inventory_tables,original_tuple)
        self.assertIs(owner._native_guest_inventory_attempts,native)
        self.assertIs(native['fictional-original-request'],marker)
        self.assertEqual(len(native),1)
        self.assertIs(owner._native_current_locked(None),False)
