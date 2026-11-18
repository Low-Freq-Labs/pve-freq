"""UNRUN fictional typed graph/snapshot DATA only; original owner port patched."""
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from test_guest_profile_current_data import ProfileCurrentData
from freq.services import pilot_guest_profile_begin_custody as source


class ProfileBeginCustodyData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileCurrentData()
        self.fixture.setUp()
        self.owner = self.fixture.owner
        self.begin = self.fixture.duty.begin
        self.original = self.begin.original
        self.store = self.fixture.fixture.store
        self.broker = source._OriginalHTTPRequests.__new__(source._OriginalHTTPRequests)
        self.server = source._OriginalPilotServer.__new__(source._OriginalPilotServer)
        self.handler = source._OriginalPilotHandler.__new__(source._OriginalPilotHandler)
        socket = object()  # Opaque graph DATA, never an acquired socket.
        self.original.socket, self.original.handler = socket, self.handler
        self.original.operation, self.original.body_taken = 'guest-owner-profile', True
        self.original.guest_response = self.begin
        self.handler.request, self.handler.server = socket, self.server
        self.broker._server, self.broker._requests, self.broker._gate = self.server, {socket: self.original}, object()
        self.server._pilot_requests = self.broker
        self.owner._server = self.server
        self.store._broker = self.broker
        self.owner._original_guest_capacity = self.owner._guest_capacity
        names = ('_auth_attempts', '_asset_attempts', '_issued_sessions', '_read_attempts',
            '_native_read_attempts', '_guest_families_by_nonce', '_guest_families_by_ref',
            '_guest_reference_records')
        for name, table in zip(names, self.owner._original_component_tables):
            setattr(self.owner, name, table)
        # New fictional unspent record, not revival of an existing record.
        prior = self.begin.record
        record = source._GuestReferenceRecord.__new__(source._GuestReferenceRecord)
        for name in source._GuestReferenceRecord.__slots__:
            setattr(record, name, getattr(prior, name))
        record._spent, record._retired = False, False
        self.begin.record = self.record = record
        self.owner._guest_reference_records[(id(self.begin.session), 'guest', self.begin.guest_ref)] = record

    @contextmanager
    def ports(self):
        with patch.object(source, '_owned_store', return_value=self.owner), patch.object(
                source._OriginalHTTPRequests, '_owned', return_value=self.original):
            yield

    def capture(self):
        self.custody = source._ProfileBeginCustody(self.store, self.handler, self.begin)
        self.selection = source._ProfileBeginSelection(self.custody, self.store, self.handler)

    def selected(self):
        return source._begin_selected_record_cleanup_data(self.custody, self.selection, self.store, self.handler)

    def test_PB01_capture_retains21and16immutable_identities_without_mutation(self):
        before = (self.record._spent, self.record._retired, self.record._ticket._remaining)
        with self.ports():
            self.capture()
            self.assertIs(self.selected(), self.record)
        self.assertEqual((len(self.custody.items), len(self.selection.items)), (21, 16))
        self.assertEqual((self.record._spent, self.record._retired, self.record._ticket._remaining), before)
        with self.assertRaises(TypeError): self.custody.items = ()
        with self.assertRaises(TypeError): del self.selection.items

    def test_PB02_spent_retired_and_removed_selected_row_remains_known_cleanup_DATA(self):
        with self.ports():
            self.capture()
            self.record._spent = self.record._retired = True
            del self.owner._guest_reference_records[(id(self.begin.session), 'guest', self.begin.guest_ref)]
            self.assertIs(self.selected(), self.record)

    def test_PB03_expiry_uncertainty_and_replaced_current_begin_fields_do_not_bar_saved_DATA(self):
        with self.ports():
            self.capture()
            self.owner._guest_capacity._uncertain = True
            self.begin.end = 0.0
            self.begin.record = object()
            self.begin.session = {}
            self.original.guest_response = object()  # Outside handoff not adopted.
            self.assertIs(self.selected(), self.record)

    def test_PB04_replaced_component_map_refuses_without_adopting_replacement(self):
        with self.ports():
            self.capture()
            old = self.owner._guest_reference_records
            self.owner._guest_reference_records = {}
            with self.assertRaises(source._RequestUnavailable): self.selected()
            self.assertIs(self.custody.items[11][7], old)
            self.assertFalse(self.record._retired)

    def test_PB05_replaced_original_request_registry_refuses_without_repair(self):
        with self.ports():
            self.capture()
            self.broker._requests[self.original.socket] = object()
            with self.assertRaises(source._RequestUnavailable): self.selected()
            self.assertFalse(self.record._retired)

    def test_PB06_replaced_captured_lock_refuses_without_acquiring_it(self):
        with self.ports():
            self.capture()
            self.broker._gate = object()
            with self.assertRaises(source._RequestUnavailable): self.selected()
            self.assertFalse(self.record._retired)

    def test_PB07_already_spent_selection_cannot_be_newly_captured(self):
        with self.ports():
            self.custody = source._ProfileBeginCustody(self.store, self.handler, self.begin)
            self.record._spent = True
            with self.assertRaises(source._RequestUnavailable):
                source._ProfileBeginSelection(self.custody, self.store, self.handler)

    def test_PB08_changed_saved_record_target_refuses_without_other_record_adoption(self):
        with self.ports():
            self.capture()
            saved = self.record._target
            self.record._target = tuple(list(saved))
            with self.assertRaises(source._RequestUnavailable): self.selected()
            self.assertIs(self.selection.items[4], saved)

    def test_PB09_foreign_snapshot_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign snapshot')
        with self.ports():
            with self.assertRaises(source._RequestUnavailable):
                source._begin_custody_matches_data(Trap(), self.store, self.handler)

    def test_PB10_foreign_store_refuses_before_handler_or_begin_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign input')
        with self.assertRaises(source._RequestUnavailable):
            source._ProfileBeginCustody(object(), Trap(), Trap())

    def test_PB11_changed_token_cannot_be_adopted_at_selected_snapshot_capture(self):
        with self.ports():
            self.custody = source._ProfileBeginCustody(self.store, self.handler, self.begin)
            original = self.begin.token
            self.begin.token = object()
            with self.assertRaises(source._RequestUnavailable):
                source._ProfileBeginSelection(self.custody, self.store, self.handler)
            self.assertIs(self.custody.items[15], original)
            self.assertFalse(self.record._spent)

    def test_PB12_equal_reconstructed_values_cannot_replace_initial_context(self):
        with self.ports():
            self.custody = source._ProfileBeginCustody(self.store, self.handler, self.begin)
            original = self.begin.values
            self.begin.values = tuple(list(original))
            self.assertEqual(self.begin.values, original)
            self.assertIsNot(self.begin.values, original)
            with self.assertRaises(source._RequestUnavailable):
                source._ProfileBeginSelection(self.custody, self.store, self.handler)
            self.assertIs(self.custody.items[17], original)
            self.assertFalse(self.record._spent)
