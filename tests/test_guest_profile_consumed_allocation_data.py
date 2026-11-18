"""UNRUN fictional read-only continuation failure priority, no original grant."""
import unittest
from unittest.mock import patch
from test_guest_profile_continuation_data import ProfileContinuationData
from freq.services import pilot_guest_profile_consumed as source


class ProfileConsumedAllocationData(unittest.TestCase):
    def setUp(self):
        self.f=ProfileContinuationData()
        self.f.setUp()
        r=self.f.record
        self.before=(r._spent,r._retired,r._last_clock,r._ticket._remaining,
                     tuple(self.f.owner._guest_reference_records.items()))

    def assert_unchanged(self):
        r=self.f.record
        self.assertEqual((r._spent,r._retired,r._last_clock,r._ticket._remaining,
                         tuple(self.f.owner._guest_reference_records.items())),self.before)

    def test_CM01_capacity_memory_keeps_same_object_without_corruption_mapping(self):
        error=MemoryError()
        with patch.object(source._GuestCapacity,'_check',side_effect=error):
            with self.assertRaises(MemoryError)as caught:self.f.lookup()
        self.assertIs(caught.exception,error)
        self.assert_unchanged()

    def test_CM02_configured_sources_memory_keeps_same_object_without_corruption_mapping(self):
        error=MemoryError()
        with patch.object(source,'_configured_sources_data',side_effect=error):
            with self.assertRaises(MemoryError)as caught:self.f.lookup()
        self.assertIs(caught.exception,error)
        self.assert_unchanged()

    def test_CM03_capacity_control_keeps_same_object_and_no_second_consume(self):
        error=KeyboardInterrupt()
        with patch.object(source._GuestCapacity,'_check',side_effect=error):
            with self.assertRaises(KeyboardInterrupt)as caught:self.f.lookup()
        self.assertIs(caught.exception,error)
        self.assert_unchanged()

    def test_CM04_configured_sources_control_keeps_same_object_and_no_second_consume(self):
        error=SystemExit()
        with patch.object(source,'_configured_sources_data',side_effect=error):
            with self.assertRaises(SystemExit)as caught:self.f.lookup()
        self.assertIs(caught.exception,error)
        self.assert_unchanged()

    def test_CM05_capacity_ordinary_validation_still_maps_to_corrupt_from_none(self):
        with patch.object(source._GuestCapacity,'_check',side_effect=ValueError('fictional')):
            with self.assertRaises(source._CorruptProfileSource)as caught:self.f.lookup()
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assert_unchanged()

    def test_CM06_configured_ordinary_validation_still_maps_to_corrupt_from_none(self):
        with patch.object(source,'_configured_sources_data',side_effect=ValueError('fictional')):
            with self.assertRaises(source._CorruptProfileSource)as caught:self.f.lookup()
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assert_unchanged()
