"""UNRUN supplied section-body/frame DATA; no authentic HTTP/profile path."""
import json
import unittest
from unittest.mock import patch

from test_guest_profile_continuation_data import ProfileContinuationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services import pilot_guest_profile_frame_data as source


STAMP = '2026-10-24T01:02:03.004Z'
COMPLETED = '2026-10-24T01:02:04.005Z'
STATUS = b'{"data":{"status":"running","cpu":0.25,"mem":1103286272,"maxmem":1073741824}}'
CONFIG = b'{"data":{}}'
NETWORK = b'{"data":{"result":[]}}'


class ProfileFrameData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileContinuationData()
        self.fixture.setUp()

    def duty(self, inputs=None):
        plan = self.fixture.plan()
        if inputs is None: inputs = ((STATUS,STAMP),(CONFIG,STAMP),(NETWORK,STAMP))
        return source._ProfileFramePreparationData(plan,inputs,COMPLETED)

    def value(self, duty):
        return json.loads(duty.frame._wire.split(b'\r\n\r\n',1)[1])

    def test_PF01_whole_qemu_profile_reports_three_sections_preserving_uncapped_memory(self):
        duty = self.duty()
        source.prepare_profile_frame_data(duty)
        value = self.value(duty)
        self.assertEqual(value['schema'],2)
        self.assertEqual(value['kind'],'guest-profile')
        self.assertEqual(value['owner_ref'],'b'*64)
        self.assertEqual(value['target'],dict(source_label='fixture-label',
            node='fixture-node',guest_kind='qemu',vmid=100,name=None))
        self.assertEqual([value[k]['outcome']for k in
            ('status','configured_network','guest_network')],['reported']*3)
        self.assertEqual(value['status']['data']['memory_used_bytes'],1103286272)
        self.assertEqual(value['status']['data']['memory_limit_bytes'],1073741824)
        self.assertEqual(value['configured_network']['data'],[])
        self.assertEqual(value['guest_network']['data'],[])
        self.assertEqual(duty.end,115.0)
        self.assertTrue(duty.begin.record._spent)
        self.assertEqual(duty.begin.record._ticket._state,'committed')

    def test_PF02_bad_status_only_unavailable_without_raw_provider_error_in_frame(self):
        duty = self.duty(((b'fictional provider secret/error',STAMP),(CONFIG,STAMP),(NETWORK,STAMP)))
        source.prepare_profile_frame_data(duty)
        value = self.value(duty)
        self.assertEqual(value['status'],dict(outcome='unavailable',observed_at=None,data=None))
        self.assertEqual(value['configured_network']['outcome'],'reported')
        self.assertEqual(value['guest_network']['outcome'],'reported')
        self.assertNotIn(b'fictional provider',duty.frame._wire)

    def test_PF03_bad_known_nic_only_configured_section_unavailable(self):
        duty = self.duty(((STATUS,STAMP),(b'{"data":{"net0":"invalid"}}',STAMP),(NETWORK,STAMP)))
        source.prepare_profile_frame_data(duty)
        value = self.value(duty)
        self.assertEqual(value['configured_network']['outcome'],'unavailable')
        self.assertEqual(value['status']['outcome'],'reported')
        self.assertEqual(value['guest_network']['outcome'],'reported')

    def test_PF04_bad_guest_network_unavailable_distinct_from_reported_empty(self):
        duty = self.duty(((STATUS,STAMP),(CONFIG,STAMP),(b'{"data":{"result":{}}}',STAMP)))
        source.prepare_profile_frame_data(duty)
        value = self.value(duty)
        self.assertEqual(value['guest_network'],dict(outcome='unavailable',observed_at=None,data=None))
        self.assertEqual(value['configured_network']['data'],[])

    def test_PF05_no_supplied_bodies_gives_all_unavailable_without_new_read(self):
        duty = self.duty(((None,None),)*3)
        source.prepare_profile_frame_data(duty)
        self.assertEqual([self.value(duty)[key]['outcome']for key in
            ('status','configured_network','guest_network')],['unavailable']*3)
        self.assertEqual(duty.begin.record._ticket._remaining,2)

    def test_PF06_lxc_all_unsupported_never_calls_qemu_decoders(self):
        target = ('fixture-node','lxc',100)
        self.fixture.record._target = self.fixture.begin.target = target
        duty = self.duty(((None,None),)*3)
        with patch.object(source,'decode_guest_status',side_effect=AssertionError('status')):
            with patch.object(source,'decode_guest_config',side_effect=AssertionError('config')):
                with patch.object(source,'decode_guest_network',side_effect=AssertionError('network')):
                    source.prepare_profile_frame_data(duty)
        self.assertEqual([self.value(duty)[key]for key in
            ('status','configured_network','guest_network')],
            [dict(outcome='unsupported',observed_at=None,data=None)]*3)

    def test_PF07_lxc_raw_is_refused_instead_of_silently_consumed_or_projected(self):
        target = ('fixture-node','lxc',100)
        self.fixture.record._target = self.fixture.begin.target = target
        with self.assertRaises(_RequestUnavailable): self.duty()

    def test_PF08_each_raw_body_cap_and_missing_timestamp_are_checked_before_parse(self):
        for inputs in (((b'x'*262145,STAMP),(None,None),(None,None)),
                ((STATUS,None),(None,None),(None,None)),
                ((None,STAMP),(None,None),(None,None))):
            with self.assertRaises(_RequestUnavailable): self.duty(inputs)
        self.assertTrue(self.fixture.record._spent)

    def test_PF09_invalid_reported_display_stamp_refuses_whole_frame_no_retry(self):
        bad = '2026-02-30T01:02:03.004Z'
        duty = self.duty(((STATUS,bad),(CONFIG,STAMP),(NETWORK,STAMP)))
        with self.assertRaises(ValueError): source.prepare_profile_frame_data(duty)
        self.assertIsNone(duty.frame)
        self.assertIsNotNone(duty.snapshot)
        self.assertEqual(duty.phase,'format-attempted')
        with self.assertRaises(_RequestUnavailable): source.prepare_profile_frame_data(duty)

    def test_PF10_retired_guest_refuses_before_format_with_charge_held(self):
        duty = self.duty()
        duty.begin.record._retire()
        with self.assertRaises(_RequestUnavailable): source.prepare_profile_frame_data(duty)
        self.assertEqual(duty.phase,'new')
        self.assertIsNone(duty.frame)
        self.assertEqual(duty.begin.record._ticket._state,'committed')

    def test_PF11_constructor_control_retains_snapshot_and_once_phase(self):
        duty = self.duty()
        control = KeyboardInterrupt('fictional frame constructor control')
        with patch.object(source,'OriginalPilotResponse',side_effect=control):
            with self.assertRaises(KeyboardInterrupt)as caught:
                source.prepare_profile_frame_data(duty)
        self.assertIs(caught.exception,control)
        self.assertIsNotNone(duty.snapshot)
        self.assertIsNone(duty.frame)
        self.assertEqual(duty.phase,'format-attempted')
        with self.assertRaises(_RequestUnavailable): source.prepare_profile_frame_data(duty)

    def test_PF12_repeat_preserves_exact_immutable_frame_and_fixed_headers(self):
        duty = self.duty()
        source.prepare_profile_frame_data(duty)
        frame = duty.frame
        with self.assertRaises(_RequestUnavailable): source.prepare_profile_frame_data(duty)
        self.assertIs(duty.frame,frame)
        with self.assertRaises(TypeError): frame._wire = b'changed'
        header,body = frame._wire.split(b'\r\n\r\n',1)
        self.assertIn(b'Content-Type: application/json; charset=utf-8\r\n',header)
        self.assertIn(b'Content-Length: '+str(len(body)).encode('ascii')+b'\r\n',header)
        self.assertIn(b'Cache-Control: no-store\r\nConnection: close\r\n',header)
        self.assertIn(b'Content-Security-Policy:',header)

    def test_PF13_original_write_end_shortening_before_holder_never_renews(self):
        self.fixture.begin.original.write_end = 114.0
        duty = self.duty()
        source.prepare_profile_frame_data(duty)
        self.assertEqual(duty.end,114.0)
        self.assertEqual(duty.begin.end,115.0)

    def test_PF14_decoder_control_propagates_without_partial_snapshot_frame_or_retry(self):
        duty = self.duty()
        control = SystemExit('fictional decoder control')
        with patch.object(source,'decode_guest_status',side_effect=control):
            with self.assertRaises(SystemExit)as caught:
                source.prepare_profile_frame_data(duty)
        self.assertIs(caught.exception,control)
        self.assertIsNone(duty.snapshot)
        self.assertIsNone(duty.frame)
        self.assertEqual(duty.phase,'format-attempted')
        with self.assertRaises(_RequestUnavailable): source.prepare_profile_frame_data(duty)

    def test_PF15_exact_decoder_body_cap_can_retain_complete_status_with_whitespace(self):
        raw = STATUS + b' '*(262144-len(STATUS))
        duty = self.duty(((raw,STAMP),(CONFIG,STAMP),(NETWORK,STAMP)))
        source.prepare_profile_frame_data(duty)
        self.assertEqual(len(duty.inputs[0][0]),262144)
        self.assertEqual(self.value(duty)['status']['outcome'],'reported')

    def test_PF16_display_timestamp_ordering_does_not_renew_captured_end(self):
        duty = self.duty(((STATUS,COMPLETED),(CONFIG,STAMP),(NETWORK,STAMP)))
        duty.completed_at = STAMP
        source.prepare_profile_frame_data(duty)
        self.assertEqual(self.value(duty)['completed_at'],STAMP)
        self.assertEqual(self.value(duty)['status']['observed_at'],COMPLETED)
        self.assertEqual(duty.end,115.0)
        self.assertEqual(duty.begin.resource_end,122.0)
