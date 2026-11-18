"""UNRUN DATA/refusal intentions. No successful original owner is constructed.

These pure family/ledger boundaries are not positive original sources reads,
actual native capacity, entropy, child issuance or source response evidence.
"""
from types import SimpleNamespace
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services import pilot_guest_sources_begin as source


class SourcesBeginData(unittest.TestCase):
    def setUp(self):
        self.session = {}
        self.values = ('fixture-user', 'viewer', 1.0, 1.0, 'fixture-csrf')
        self.generation = 'fixture-source-revision'
        self.cohort = SimpleNamespace(nodes=())
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_families_by_nonce={}, _guest_families_by_ref={})
        ticket = self.owner._guest_capacity._reserve(self.session, self.values[0], 1)
        self.family = _GuestFamilyRecord(self.session, self.values[0], 'a'*64,
            self.cohort, self.generation, object(), 100.0, 130.0, ticket)
        self.owner._guest_capacity._commit(ticket)
        self.family._bind_once('b'*64)
        self.owner._guest_families_by_nonce[(id(self.session), 'a'*64)] = self.family
        self.owner._guest_families_by_ref[(id(self.session), 'b'*64)] = self.family
        self.original = SimpleNamespace(end=125.0, write_end=120.0)

    def lookup(self, session=None, principal='fixture-user', reference=None,
               cohort=None, generation=None, now=110.0):
        return source._source_family_data_locked(self.owner,
            self.session if session is None else session, principal,
            'b'*64 if reference is None else reference,
            self.cohort if cohort is None else cohort,
            self.generation if generation is None else generation, now)

    def duty(self, count):
        d = source._GuestSourcesBeginDuty(self.original, 'fixture-token',
            self.session, self.values, 'b'*64)
        d.family = self.family
        d.sources = tuple(object() for _ in range(count))  # Count DATA only.
        self.family._sources_spent = True
        d.phase = 'spent'
        return d

    def test_SB01_lookup_is_same_private_family_and_does_not_consume(self):
        self.assertIs(self.lookup(), self.family)
        self.assertFalse(self.family._sources_spent)
        self.assertEqual(self.owner._guest_capacity._check()[0], 1)

    def test_SB02_foreign_equal_session_cannot_select_or_consume(self):
        with self.assertRaises(_RequestUnavailable): self.lookup(session={})
        self.assertFalse(self.family._sources_spent)

    def test_SB03_other_principal_refuses(self):
        with self.assertRaises(source._CorruptSourceFamily): self.lookup(principal='other')
        self.assertFalse(self.family._sources_spent)

    def test_SB04_old_Cluster_shape_cannot_be_family(self):
        for ref in ('b'*32, 'B'*64, 'b'*63, 'b'*65):
            with self.assertRaises(_RequestUnavailable): self.lookup(reference=ref)
        self.assertFalse(self.family._sources_spent)

    def test_SB05_wrong_F_cannot_consume_another_family(self):
        with self.assertRaises(_RequestUnavailable): self.lookup(reference='c'*64)
        self.assertFalse(self.family._sources_spent)

    def test_SB06_present_None_index_is_corruption_not_missing(self):
        self.owner._guest_families_by_ref[(id(self.session), 'b'*64)] = None
        with self.assertRaises(source._CorruptSourceFamily): self.lookup()

    def test_SB07_missing_nonce_or_ticket_cannot_select(self):
        del self.owner._guest_families_by_nonce[(id(self.session), 'a'*64)]
        with self.assertRaises(source._CorruptSourceFamily): self.lookup()
        self.owner._guest_families_by_nonce[(id(self.session), 'a'*64)] = self.family
        del self.owner._guest_capacity._tickets[id(self.family._ticket)]
        with self.assertRaises(source._CorruptSourceFamily): self.lookup()

    def test_SB08_expiry_and_backwards_clock_retain_only_closed_candidate_DATA(self):
        for now in (99.0, 130.0, 131.0):
            with self.assertRaises(source._ExpiredSourceFamily) as caught:
                self.lookup(now=now)
            self.assertIs(caught.exception.family, self.family)
        # Predicate itself is read-only; only guarded original caller retires.
        self.assertEqual(self.family._state, 'live')

    def test_SB09_retired_or_changed_cohort_cannot_resume(self):
        with self.assertRaises(source._ExpiredSourceFamily): self.lookup(cohort=object())
        with self.assertRaises(source._ExpiredSourceFamily): self.lookup(generation=object())
        self.family._retire()
        with self.assertRaises(source._ExpiredSourceFamily): self.lookup()

    def test_SB10_nonfinite_and_nonfloat_clock_refuse(self):
        for now in (110, True, float('nan'), float('inf')):
            with self.assertRaises(_RequestUnavailable): self.lookup(now=now)

    def test_SB11_duty_retains_first_write_end_without_native_work(self):
        d = self.duty(1)
        self.original.write_end = 124.0
        self.assertEqual(d.initial_write_end, 120.0)
        self.assertEqual(d.end, 120.0)
        self.assertIs(d.original, self.original)
        self.assertIsNone(d.ticket)

    def test_SB12_session512_reserves_whole32_before_any_record(self):
        self.owner._guest_capacity._reserve(self.session, self.values[0], 256)
        self.owner._guest_capacity._reserve(self.session, self.values[0], 223)
        d = self.duty(32)
        self.assertTrue(source._reserve_source_ticket_data_locked(self.owner, d))
        self.assertEqual(d.ticket._remaining, 32)
        self.assertEqual(d.ticket._state, 'reserved')
        self.assertEqual(self.owner._guest_capacity._check()[0], 512)

    def test_SB13_session513_refuses_zero_new_tickets_and_stays_spent(self):
        self.owner._guest_capacity._reserve(self.session, self.values[0], 256)
        self.owner._guest_capacity._reserve(self.session, self.values[0], 224)
        d = self.duty(32)
        before = dict(self.owner._guest_capacity._tickets)
        self.assertFalse(source._reserve_source_ticket_data_locked(self.owner, d))
        self.assertEqual(self.owner._guest_capacity._tickets, before)
        self.assertIsNone(d.ticket)
        self.assertTrue(self.family._sources_spent)
        self.assertFalse(self.owner._guest_capacity._uncertain)

    def fill_other_sessions(self):
        for _ in range(7):
            session = {}
            for _ in range(2): self.owner._guest_capacity._reserve(session, 'other', 256)

    def test_SB14_owner4096_exact_full_reservation_DATA(self):
        self.owner._guest_capacity._reserve(self.session, self.values[0], 256)
        self.owner._guest_capacity._reserve(self.session, self.values[0], 223)
        self.fill_other_sessions()
        d = self.duty(32)
        self.assertTrue(source._reserve_source_ticket_data_locked(self.owner, d))
        self.assertEqual(self.owner._guest_capacity._check()[0], 4096)

    def test_SB15_owner4097_refuses_with_session_capacity_remaining(self):
        self.owner._guest_capacity._reserve(self.session, self.values[0], 256)
        self.owner._guest_capacity._reserve(self.session, self.values[0], 223)
        self.fill_other_sessions()
        self.owner._guest_capacity._reserve({}, 'other-extra', 1)
        d = self.duty(32)
        before = dict(self.owner._guest_capacity._tickets)
        self.assertFalse(source._reserve_source_ticket_data_locked(self.owner, d))
        self.assertEqual(self.owner._guest_capacity._tickets, before)
        self.assertTrue(self.family._sources_spent)

    def test_SB16_empty_source_list_has_explicit_zero_ticket_duty(self):
        d = self.duty(0)
        self.assertTrue(source._reserve_source_ticket_data_locked(self.owner, d))
        self.assertEqual(d.ticket._remaining, 0)
        self.assertIs(self.owner._guest_capacity._tickets[id(d.ticket)], d.ticket)
        self.owner._guest_capacity._retire_unpublished(d.ticket)
        self.assertEqual(d.ticket._state, 'retired')
        self.assertEqual(self.owner._guest_capacity._check()[0], 1)
        self.assertTrue(self.family._sources_spent)

    def test_SB17_unspent_or_repeated_reservation_refuses(self):
        d = self.duty(1)
        self.family._sources_spent = False
        with self.assertRaises(_RequestUnavailable): source._reserve_source_ticket_data_locked(self.owner, d)
        self.family._sources_spent = True
        self.assertTrue(source._reserve_source_ticket_data_locked(self.owner, d))
        with self.assertRaises(_RequestUnavailable): source._reserve_source_ticket_data_locked(self.owner, d)

    def test_SB18_configured_rows_preserve_original_objects_and_order(self):
        rows = tuple(('label'+str(i), TargetSnapshot(self.generation, 'node'+str(i), '192.0.2.'+str(i+1))) for i in range(32))
        self.cohort.nodes = rows
        self.assertIs(source._configured_sources_data(self.cohort, self.generation), rows)
        self.cohort.nodes = rows + (rows[0],)
        with self.assertRaises(_RequestUnavailable): source._configured_sources_data(self.cohort, self.generation)

    def test_SB19_equal_foreign_revision_cannot_replace_original_identity(self):
        foreign = self.generation.encode().decode()
        self.assertEqual(foreign, self.generation)
        self.assertIsNot(foreign, self.generation)
        self.cohort.nodes = (('label', TargetSnapshot(foreign, 'node', '192.0.2.1')),)
        with self.assertRaises(_RequestUnavailable): source._configured_sources_data(self.cohort, self.generation)

    def test_SB20_supplied_store_refuses_before_handler_hooks(self):
        class Handler:
            def __getattribute__(self, name):
                raise AssertionError('Foreign store reached handler')
        for operation in (source.begin_sources, source.abandon_sources_begin):
            with self.assertRaises(_RequestUnavailable): operation(object(), Handler())


if __name__ == '__main__':
    unittest.main()
