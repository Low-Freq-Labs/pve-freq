"""UNRUN pure holder/count retirement intentions; no positive original owner.

The reused fixture is fictional DATA. It creates no original handler/server,
locks, custody authority, native attempt, physical allowance or cleanup receipt.
Self-quarantine flags here test only DATA helper independence, not the guarded
original retirement entry. No candidate test has run on any target.
"""
import unittest
from unittest.mock import patch

from test_guest_inventory_registration_data import InventoryRegistrationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_inventory_registration as registration
from freq.services import pilot_guest_inventory_retirement as source


class InventoryRetirementData(unittest.TestCase):
    def setUp(self):
        # Reuse setup explicitly, without inheriting/rerunning its test methods.
        self.fixture = InventoryRegistrationData()
        self.fixture.setUp()
        self.duty = self.fixture.duty()
        registration._register_inventory_duty_data(self.fixture.owner, self.duty)

    def test_IT01_known_logical_retirement_retains_source_charge_and_native_duty(self):
        f, duty = self.fixture, self.duty
        self.assertIsNone(source._retire_unstarted_holders_data(duty, None))
        source._retire_registration_data(duty)
        self.assertTrue(f.record._spent)
        self.assertTrue(f.record._retired)
        self.assertEqual(f.owner._guest_capacity._check()[0], 2)
        self.assertNotIn(duty.original, f.owner._guest_inventory_attempts)
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)
        self.assertEqual(duty.charge, 15442019)

    def test_IT02_own_quarantine_DATA_flags_do_not_require_positive_capacity_check(self):
        # No claim of successful original snapshot/gate path from these flags.
        f, duty = self.fixture, self.duty
        f.owner._guest_capacity._uncertain = True
        f.store._broker._live = False
        self.assertIsNone(source._retire_unstarted_holders_data(duty, None))
        source._retire_registration_data(duty)
        self.assertTrue(f.owner._guest_capacity._uncertain)
        self.assertFalse(f.store._broker._live)
        self.assertTrue(f.record._spent and f.record._retired)
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)

    def test_IT03_known_native_after_seeded_partial_registration_can_retire_logical_DATA(self):
        f, duty = self.fixture, self.duty
        duty.phase = 'registration-pending'
        del f.owner._guest_inventory_attempts[duty.original]
        self.assertIsNone(source._retire_unstarted_holders_data(duty, None))
        source._retire_registration_data(duty)
        self.assertEqual(duty.phase, 'retired')
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)
        self.assertEqual(f.owner._guest_inventory_attempts, {})

    def test_IT04_unknown_missing_native_registration_is_not_reconstructed(self):
        f, duty = self.fixture, self.duty
        duty.phase = 'registration-pending'
        del f.owner._guest_inventory_attempts[duty.original]
        del f.owner._native_guest_inventory_attempts[duty.original]
        self.assertIsNone(source._retire_unstarted_holders_data(duty, None))
        with self.assertRaises(_RequestUnavailable):
            source._retire_registration_data(duty)
        self.assertEqual(duty.phase, 'registration-pending')
        self.assertEqual(f.owner._native_guest_inventory_attempts, {})
        self.assertTrue(f.record._spent and f.record._retired)

    def test_IT05_present_None_selected_row_is_corrupt_never_treated_as_absent(self):
        f, duty = self.fixture, self.duty
        f.owner._guest_inventory_attempts[duty.original] = None
        with self.assertRaises(_RequestUnavailable):
            source._retire_registration_data(duty)
        self.assertIn(duty.original, f.owner._guest_inventory_attempts)
        self.assertIsNone(f.owner._guest_inventory_attempts[duty.original])
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)

    def test_IT06_unknown_slot_refuses_without_calling_supplied_native_hooks(self):
        class Trap:
            def __getattribute__(self, name):
                raise AssertionError('supplied native hook reached')
        f, duty = self.fixture, self.duty
        held = Trap()
        duty.slot.attempt = held
        error = source._retire_unstarted_holders_data(duty, None)
        self.assertIsInstance(error, _RequestUnavailable)
        self.assertTrue(f.record._retired)
        self.assertIs(duty.slot.attempt, held)
        self.assertIs(f.owner._guest_inventory_attempts[duty.original], duty)

    def test_IT07_wrong_source_identity_is_not_retired_as_the_original_source(self):
        f, duty = self.fixture, self.duty
        f.record._source = (f.row[0], f.row[1])
        error = source._retire_unstarted_holders_data(duty, None)
        self.assertIsInstance(error, _RequestUnavailable)
        self.assertFalse(f.record._retired)
        self.assertTrue(f.record._spent)
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)

    def test_IT08_genuine_source_control_stays_first_and_registration_is_retained(self):
        f, duty = self.fixture, self.duty
        control = KeyboardInterrupt('fixture original control')
        duty.slot.phase = 'unknown'
        with patch.object(_GuestReferenceRecord, '_retire', side_effect=control):
            error = source._retire_unstarted_holders_data(duty, None)
        self.assertIs(error, control)
        self.assertIs(f.owner._guest_inventory_attempts[duty.original], duty)
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)
        self.assertEqual(duty.charge, 15442019)

    def test_IT09_repeated_known_native_DATA_retirement_keeps_same_tombstone(self):
        f, duty = self.fixture, self.duty
        for _ in range(2):
            self.assertIsNone(source._retire_unstarted_holders_data(duty, None))
            source._retire_registration_data(duty)
        self.assertEqual(duty.phase, 'retired')
        self.assertIs(f.owner._native_guest_inventory_attempts[duty.original], duty)
        self.assertEqual(f.owner._guest_capacity._check()[0], 2)

    def test_IT10_foreign_store_refuses_before_handler_hooks(self):
        class HandlerTrap:
            def __getattribute__(self, name):
                raise AssertionError('foreign handler hook reached')
        with self.assertRaises(_RequestUnavailable):
            source.retire_inventory_handler_duty(object(), HandlerTrap())
