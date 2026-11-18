"""UNRUN pure prepared-row/refusal intentions, never an original issuer test."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_sources_begin import _GuestSourcesBeginDuty
from freq.services import pilot_guest_sources_response as source


class SourcesIssuanceData(unittest.TestCase):
    def setUp(self):
        self.session, self.generation = {}, 'fixture-generation'
        self.values = ('fixture-user', 'viewer', 1.0, 1.0, 'fixture-csrf')
        self.rows = tuple(('label'+str(i), TargetSnapshot(self.generation,
            'node'+str(i), '192.0.2.'+str(i+1))) for i in range(2))
        self.cohort = SimpleNamespace(nodes=self.rows)
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(), _guest_reference_records={})
        capacity = self.owner._guest_capacity
        family_ticket = capacity._reserve(self.session, self.values[0], 1)
        self.family = _GuestFamilyRecord(self.session, self.values[0], 'a'*64,
            self.cohort, self.generation, object(), 90.0, 120.0, family_ticket)
        capacity._commit(family_ticket)
        self.family._bind_once('b'*64)
        self.family._sources_spent = True
        original = SimpleNamespace(end=140.0, write_end=130.0)
        begin = _GuestSourcesBeginDuty(original, 'fixture-token', self.session,
            self.values, 'b'*64)
        begin.family, begin.cohort, begin.generation = self.family, self.cohort, self.generation
        begin.created, begin.resource_end, begin.end = 100.0, 110.0, 110.0
        begin.sources = self.rows
        begin.ticket = capacity._reserve(self.session, self.values[0], 2)
        begin.phase = 'reserved'
        self.duty = source._SourcesIssueDuty(object(), original, begin)
        self.duty.candidates = ('c'*64, 'd'*64)  # Explicitly supplied DATA only.
        for row, key in zip(self.rows, self.duty.candidates):
            self.duty.records.append(_GuestReferenceRecord(key, 'source',
                self.session, self.values[0], row, self.generation, self.cohort,
                None, 100.0, 120.0, begin.ticket, self.family))

    def prepared(self):
        return source._prepared_records_data(self.duty)

    def test_SI01_holder_has_no_acquiring_method_or_authority(self):
        self.assertFalse(hasattr(self.duty, 'acquire'))
        self.assertFalse(hasattr(self.duty, 'run'))
        self.assertEqual(self.duty.native_phase, 'armed')
        self.assertIsNone(self.duty.frame)

    def test_SI02_prepared_DATA_creates_no_index_or_commit(self):
        self.assertIsNone(self.prepared())
        self.assertEqual(self.owner._guest_reference_records, {})
        self.assertEqual(self.duty.begin.ticket._state, 'reserved')
        self.assertEqual(self.duty.begin.ticket._remaining, 2)

    def test_SI03_partial_records_cannot_validate(self):
        self.duty.records.pop()
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI04_duplicate_candidates_refuse_whole_list(self):
        self.duty.candidates = ('c'*64, 'c'*64)
        self.duty.records[1]._key = 'c'*64
        with self.assertRaises(_RequestUnavailable): self.prepared()
        self.assertEqual(self.owner._guest_reference_records, {})

    def test_SI05_wrong_purpose_cannot_be_source(self):
        self.duty.records[0]._purpose = 'guest'
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI06_equal_foreign_session_cannot_replace_identity(self):
        self.duty.records[0]._session = {}
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI07_equal_foreign_source_row_cannot_replace_original(self):
        row = self.rows[0]
        self.duty.records[0]._source = (row[0], row[1])
        self.assertEqual(self.duty.records[0]._source, row)
        self.assertIsNot(self.duty.records[0]._source, row)
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI08_replaced_family_cohort_generation_or_ticket_refuse(self):
        record = self.duty.records[0]
        for field in ('_family', '_cohort', '_generation', '_ticket'):
            old = getattr(record, field)
            setattr(record, field, object())
            with self.assertRaises(_RequestUnavailable): self.prepared()
            setattr(record, field, old)

    def test_SI09_spent_or_retired_record_cannot_publish(self):
        record = self.duty.records[0]
        record._spent = True
        with self.assertRaises(_RequestUnavailable): self.prepared()
        record._spent, record._retired = False, True
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI10_record_expiry_or_creation_cannot_renew(self):
        record = self.duty.records[0]
        record._expires = 121.0
        with self.assertRaises(_RequestUnavailable): self.prepared()
        record._expires, record._created = 120.0, 101.0
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def existing(self, purpose='source', foreign=False):
        capacity = self.owner._guest_capacity
        session, family = self.session, self.family
        if foreign:
            session = {}
            ticket = capacity._reserve(session, 'fixture-user', 1)
            family = _GuestFamilyRecord(session, 'fixture-user', 'a'*64,
                self.cohort, self.generation, object(), 90.0, 120.0, ticket)
            capacity._commit(ticket)
            family._bind_once('b'*64)
        ticket = capacity._reserve(session, 'fixture-user', 1)
        record = _GuestReferenceRecord('c'*64, purpose, session, 'fixture-user',
            self.rows[0], self.generation, self.cohort,
            None if purpose == 'source' else object(), 100.0, 120.0, ticket, family)
        capacity._commit(ticket)
        key = (id(session), purpose, record._key)
        self.owner._guest_reference_records[key] = record
        return key, record

    def test_SI11_same_session_purpose_collision_detected_without_mutation(self):
        key, record = self.existing()
        self.assertTrue(source._existing_source_keys_data(self.owner, self.duty))
        self.assertIs(self.owner._guest_reference_records[key], record)
        self.assertEqual(self.duty.begin.ticket._state, 'reserved')

    def test_SI12_equal_guest_purpose_R_is_not_source_collision(self):
        self.existing(purpose='guest')
        self.assertFalse(source._existing_source_keys_data(self.owner, self.duty))

    def test_SI13_equal_foreign_session_R_cannot_cross_select(self):
        self.existing(foreign=True)
        self.assertFalse(source._existing_source_keys_data(self.owner, self.duty))

    def test_SI14_malformed_or_missing_existing_ticket_refuses(self):
        key, record = self.existing()
        del self.owner._guest_capacity._tickets[id(record._ticket)]
        with self.assertRaises(_RequestUnavailable): source._existing_source_keys_data(self.owner, self.duty)
        self.owner._guest_reference_records = {'malformed': object()}
        with self.assertRaises(_RequestUnavailable): source._existing_source_keys_data(self.owner, self.duty)

    def test_SI15_DATA_clock_advances_only_within_same_earlier_end(self):
        with patch.object(source.time, 'monotonic', return_value=105.0):
            self.assertEqual(source._earlier_clock(self.duty), 105.0)
        self.assertEqual(self.duty.last_clock, 105.0)
        self.assertEqual(self.duty.end, 110.0)

    def test_SI16_backwards_expired_nonfinite_DATA_clock_refuses(self):
        for now in (99.0, 110.0, 111.0, float('nan'), float('inf'), 105):
            with patch.object(source.time, 'monotonic', return_value=now):
                with self.assertRaises(_RequestUnavailable): source._earlier_clock(self.duty)
        self.assertEqual(self.duty.last_clock, 100.0)
        self.assertEqual(self.duty.end, 110.0)

    def test_SI17_foreign_store_refuses_before_handler_or_native_hooks(self):
        class Handler:
            def __getattribute__(self, name):
                raise AssertionError('Foreign store reached handler')
        for operation in (source.admit_sources_response, source.retire_sources_handler_duty):
            with self.assertRaises(_RequestUnavailable): operation(object(), Handler())
        with self.assertRaises(_RequestUnavailable): source.write_sources_response(object(), Handler(), object())

    def test_SI18_empty_preparation_requires_exact_empty_containers(self):
        self.duty.begin.sources = ()
        self.duty.candidates, self.duty.records = (), []
        self.assertIsNone(self.prepared())
        self.duty.candidates = []
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI19_missing_native_return_cannot_validate_prepared_DATA(self):
        self.duty.candidates = None
        with self.assertRaises(_RequestUnavailable): self.prepared()
        self.assertIsNone(self.duty.frame)

    def test_SI20_subclass_or_unknown_record_container_refuses(self):
        class Rows(list): pass
        self.duty.records = Rows(self.duty.records)
        with self.assertRaises(_RequestUnavailable): self.prepared()

    def test_SI21_known_holder_loop_retires_every_record_without_refund(self):
        before = dict(self.owner._guest_capacity._tickets)
        self.assertIsNone(source._retire_retained_records_data(self.duty, None))
        self.assertTrue(all(r._retired for r in self.duty.records))
        self.assertEqual(self.owner._guest_capacity._tickets, before)
        self.assertEqual(self.duty.begin.ticket._remaining, 2)

    def test_SI22_holder_control_does_not_skip_later_known_record(self):
        class Control(BaseException): pass
        control, attempted = Control(), []
        first, later = self.duty.records
        original = _GuestReferenceRecord._retire
        def retire(record):
            attempted.append(record)
            if record is first: raise control
            original(record)
        with patch.object(_GuestReferenceRecord, '_retire', new=retire):
            self.assertIs(source._retire_retained_records_data(self.duty, None), control)
        self.assertEqual(attempted, [first, later])
        self.assertTrue(later._retired)
        self.assertEqual(self.duty.begin.ticket._state, 'reserved')

    def test_SI23_existing_genuine_control_wins_and_all_holders_attempted(self):
        class Control(BaseException): pass
        first, later = Control(), Control()
        attempted = []
        def retire(record):
            attempted.append(record)
            raise later
        with patch.object(_GuestReferenceRecord, '_retire', new=retire):
            self.assertIs(source._retire_retained_records_data(self.duty, first), first)
        self.assertEqual(attempted, self.duty.records)

    def test_SI24_cleanup_control_outranks_ordinary_body_failure(self):
        class Control(BaseException): pass
        control = Control()
        with patch.object(_GuestReferenceRecord, '_retire', side_effect=control) as retire:
            self.assertIs(source._retire_retained_records_data(self.duty, ValueError()), control)
        self.assertEqual(retire.call_count, 2)

    def test_SI25_bad_retained_row_does_not_skip_known_valid_holders(self):
        self.duty.records.insert(0, object())
        result = source._retire_retained_records_data(self.duty, None)
        self.assertIsInstance(result, _RequestUnavailable)
        self.assertTrue(all(r._retired for r in self.duty.records[1:]))
        self.assertEqual(self.duty.begin.ticket._remaining, 2)

    def test_SI26_pure_holder_retirement_works_with_uncertain_capacity_DATA(self):
        self.owner._guest_capacity._uncertain = True
        self.assertIsNone(source._retire_retained_records_data(self.duty, None))
        self.assertTrue(all(r._retired for r in self.duty.records))
        self.assertTrue(self.owner._guest_capacity._uncertain)
        self.assertEqual(self.duty.begin.ticket._remaining, 2)

    def test_SI27_custody_DATA_is_immutable_and_does_not_authenticate(self):
        data = object.__new__(source._SourcesRetirementCustody)
        object.__setattr__(data, '_items', ('explicit non-authoritative DATA',))
        with self.assertRaises(TypeError): data._items = ()
        with self.assertRaises(TypeError): del data._items
        self.assertIsNotNone(data._items)

    def test_SI28_foreign_cleanup_graph_refuses_before_original_handler_access(self):
        class Handler:
            def __getattribute__(self, name):
                raise AssertionError('Foreign cleanup reached handler')
        with self.assertRaises(_RequestUnavailable): source._retirement_original(object(), Handler())
        with self.assertRaises(_RequestUnavailable): source._retirement_custody_matches(object(), object(), Handler(), self.duty)


if __name__ == '__main__':
    unittest.main()
