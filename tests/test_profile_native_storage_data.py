"""UNRUN pending profile storage DATA, no original native owner or executor."""
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.pilot_component_binding import _OriginalPilotComponentBinding


class ProfileNativeStorageData(unittest.TestCase):
    def prepared(self):
        owner = OriginalPilotInstallation()
        owner._prepare_pending_original()
        return owner

    def test_PS01_profile_slots_None_before_any_pure_preparation(self):
        owner = OriginalPilotInstallation()
        for name in ('_guest_profile_attempts','_native_guest_profile_attempts',
                '_original_guest_profile_tables','_server','_gate'):
            self.assertIsNone(getattr(owner,name))
        self.assertIs(owner._native_current_locked(None),False)

    def test_PS02_original_nine_inventory_two_profile_two_maps_are_distinct_DATA(self):
        owner = self.prepared()
        old, inventory, profile = (owner._original_component_tables,
            owner._original_guest_inventory_tables,owner._original_guest_profile_tables)
        self.assertEqual((len(old),len(inventory),len(profile)),(9,2,2))
        self.assertEqual(len({id(table)for table in old+inventory+profile}),13)
        self.assertTrue(all(type(table)is dict and not table for table in old+inventory+profile))
        self.assertIs(profile[0],owner._guest_profile_attempts)
        self.assertIs(profile[1],owner._native_guest_profile_attempts)
        self.assertTrue(owner._original_guest_profile_tables_current())
        self.assertIs(owner._native_current_locked(None),False)
        self.assertIsNone(owner._gate)
        self.assertIsNone(owner._server)

    def test_PS03_aliases_to_old_inventory_or_profile_maps_refuse_without_repair(self):
        for which in ('old','inventory','profile'):
            owner = self.prepared()
            old, inventory, profile = (owner._original_component_tables,
                owner._original_guest_inventory_tables,owner._original_guest_profile_tables)
            if which=='old': owner._guest_profile_attempts = old[4]
            elif which=='inventory': owner._guest_profile_attempts = inventory[1]
            else: owner._guest_profile_attempts = profile[1]
            self.assertFalse(owner._original_guest_profile_tables_current())
            self.assertIs(owner._original_guest_profile_tables,profile)
            self.assertTrue(owner._original_component_tables_current())
            self.assertTrue(owner._original_guest_inventory_tables_current())
            self.assertEqual(profile,({},{}))

    def test_PS04_replaced_profile_tuple_or_map_refuses_without_new_storage(self):
        for which in ('tuple','map'):
            owner = self.prepared()
            original = owner._original_guest_profile_tables
            if which=='tuple': owner._original_guest_profile_tables = ({},{})
            else: owner._native_guest_profile_attempts = {}
            self.assertFalse(owner._original_guest_profile_tables_current())
            self.assertEqual(original,({},{}))
            self.assertIs(owner._native_current_locked(None),False)

    def test_PS05_sixtyfour_count_only_DATA_is_not_native_and_sixtyfive_refuses(self):
        for field in ('_guest_profile_attempts','_native_guest_profile_attempts'):
            owner = self.prepared()
            table = getattr(owner,field)
            for index in range(64): table[index] = object()  # Fictional count DATA only.
            self.assertTrue(owner._original_guest_profile_tables_current())
            self.assertIs(owner._native_current_locked(None),False)
            marker = object()
            table[64] = marker
            self.assertFalse(owner._original_guest_profile_tables_current())
            self.assertEqual(len(table),65)
            self.assertIs(table[64],marker)

    def test_PS06_own_capacity_uncertainty_refuses_positive_filter_but_keeps_native_duty(self):
        owner = self.prepared()
        tables = owner._original_guest_profile_tables
        marker = object()
        tables[1]['fictional-original-request'] = marker
        owner._guest_capacity._uncertain = True
        self.assertFalse(owner._original_guest_profile_tables_current())
        self.assertIs(owner._original_guest_profile_tables,tables)
        self.assertIs(owner._native_guest_profile_attempts,tables[1])
        self.assertIs(tables[1]['fictional-original-request'],marker)
        self.assertIs(owner._native_current_locked(None),False)

    def test_PS07_repeat_prepare_never_replaces_any_original_tuple(self):
        owner = self.prepared()
        old, inventory, profile = (owner._original_component_tables,
            owner._original_guest_inventory_tables,owner._original_guest_profile_tables)
        with self.assertRaises(_RequestUnavailable): owner._prepare_pending_original()
        self.assertIs(owner._original_component_tables,old)
        self.assertIs(owner._original_guest_inventory_tables,inventory)
        self.assertIs(owner._original_guest_profile_tables,profile)
        self.assertEqual(owner._pending_state,'prepared')

    def test_PS08_foreign_owner_filter_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign owner hook')
        self.assertIs(_OriginalPilotComponentBinding._original_guest_profile_tables_current(
            Trap()),False)
