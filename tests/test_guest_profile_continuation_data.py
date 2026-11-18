"""UNRUN spent-guest continuation/subread plan DATA; no native operations."""
import unittest

from test_guest_profile_begin_data import ProfileBeginData
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services import pilot_guest_profile_begin as begin_source
from freq.services import pilot_guest_profile_consumed as source
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData


class ProfileContinuationData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileBeginData()
        self.fixture.setUp()
        f = self.fixture.f
        self.owner,self.record = f.owner,self.fixture.record
        begin_source._consume_profile_guest_data(self.record,112.0)
        original = _OriginalRequest(object(),115.0,'192.0.2.2')
        self.begin = begin_source._GuestProfileBeginDuty(original,'fixture-token',
            f.session,f.values,'b'*64,self.record._key)
        b = self.begin
        b.family,b.record,b.source,b.target = f.family,self.record,self.record._source,self.record._target
        b.cohort,b.generation = f.cohort,f.generation
        b.created,b.resource_end,b.phase = 112.0,122.0,'spent'
        original.guest_response = b
        original.operation,original.body_taken = 'guest-owner-profile',True

    def lookup(self, now=112.5):
        b = self.begin
        return source.consumed_profile_guest_data_locked(self.owner,b.family,
            b.session,b.values[0],b.guest_ref,b.cohort,b.generation,now)

    def plan(self, now=112.5):
        return _GuestProfileSubreadsData(self.owner,self.begin,now)

    def test_PC01_consumed_lookup_returns_same_record_without_second_consume_or_clock(self):
        before = (self.record._spent,self.record._retired,self.record._last_clock,
            self.owner._guest_capacity._check()[0])
        self.assertIs(self.lookup(),self.record)
        self.assertEqual((self.record._spent,self.record._retired,self.record._last_clock,
            self.owner._guest_capacity._check()[0]),before)

    def test_PC02_unspent_guest_cannot_be_adopted_as_continuation(self):
        self.record._spent = False
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertFalse(self.record._spent)
        self.assertEqual(self.record._last_clock,112.0)

    def test_PC03_retired_guest_cannot_be_revived(self):
        self.record._retire()
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertTrue(self.record._retired)

    def test_PC04_expired_or_backward_now_refuses_without_updating_record_clock(self):
        before = (self.record._spent,self.record._retired,self.record._last_clock)
        for now in (111.0,120.0,float('nan')):
            with self.assertRaises(_RequestUnavailable): self.lookup(now)
            self.assertEqual((self.record._spent,self.record._retired,self.record._last_clock),before)

    def test_PC05_equal_reconstructed_source_is_not_original_configured_row(self):
        self.record._source = tuple(list(self.record._source))
        with self.assertRaises(begin_source._CorruptProfileSource): self.lookup()
        self.assertEqual(self.record._last_clock,112.0)

    def test_PC06_source_purpose_reference_has_no_guest_continuation_fallback(self):
        self.begin.guest_ref = self.fixture.f.record._key
        with self.assertRaises(_RequestUnavailable): self.lookup()
        self.assertTrue(self.record._spent)

    def test_PC07_equal_foreign_session_cannot_reconstruct_plan(self):
        self.begin.session = {}
        with self.assertRaises(_RequestUnavailable): self.plan()
        self.assertEqual(self.record._last_clock,112.0)

    def test_PC08_qemu_plan_has_only_three_fixed_GETs_and_existing_body_caps(self):
        plan = self.plan()
        prefix = '/api2/json/nodes/fixture-node/qemu/100'
        self.assertEqual(plan.reads,(
            ('status','GET',prefix+'/status/current',262144),
            ('configured_network','GET',prefix+'/config',262144),
            ('guest_network','GET',prefix+'/agent/network-get-interfaces',262144)))
        self.assertEqual(plan.unsupported_sections,())
        self.assertIs(plan.begin,self.begin)
        self.assertIs(plan.source,self.fixture.f.row)
        self.assertIs(plan.target,self.record._target)
        self.assertEqual(plan.end,115.0)

    def test_PC09_lxc_plan_has_no_reads_and_all_sections_unsupported(self):
        target = ('fixture-node','lxc',100)
        self.record._target = self.begin.target = target
        plan = self.plan()
        self.assertEqual(plan.reads,())
        self.assertEqual(plan.unsupported_sections,
            ('status','configured_network','guest_network'))

    def test_PC10_target_path_injection_or_bool_vmid_refuses_before_plan(self):
        for target in (('node/other','qemu',100),('n','qemu',True),
                ('n','qemu?x','100'),('n','qemu',1000000000)):
            self.record._target = self.begin.target = target
            with self.assertRaises(_RequestUnavailable): self.plan()

    def test_PC11_shorter_original_write_end_is_captured_without_renewal(self):
        self.begin.original.write_end = 114.0
        plan = self.plan()
        self.assertEqual(plan.end,114.0)
        self.assertEqual(self.begin.end,115.0)
        with self.assertRaises(_RequestUnavailable): self.plan(114.0)

    def test_PC12_extended_original_write_end_cannot_replace_first_bound(self):
        self.begin.original.write_end = 116.0
        with self.assertRaises(_RequestUnavailable): self.plan()
        self.assertEqual(self.begin.end,115.0)

    def test_PC13_plan_is_immutable_but_not_deep_original_authority(self):
        plan = self.plan()
        with self.assertRaises(TypeError): plan.end = 122.0
        with self.assertRaises(TypeError): del plan.source
        self.assertIs(plan.begin,self.begin)  # Mutable original graph needs revalidation.

    def test_PC14_replaced_original_duty_cannot_construct_plan(self):
        self.begin.original.guest_response = object()
        with self.assertRaises(_RequestUnavailable): self.plan()

    def test_PC15_nonfinite_or_nonfloat_plan_now_cannot_renew(self):
        for now in (True,112,float('nan'),float('inf')):
            with self.assertRaises(_RequestUnavailable): self.plan(now)
        self.assertEqual(self.begin.end,115.0)

    def test_PC16_reconstruction_at_original_end_refuses_no_new_attempt(self):
        plan = self.plan()
        with self.assertRaises(_RequestUnavailable): self.plan(115.0)
        self.assertEqual(plan.end,115.0)
        self.assertEqual(self.begin.resource_end,122.0)
        self.assertTrue(self.record._spent)
