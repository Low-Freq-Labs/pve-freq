"""UNRUN whole inventory response DATA; no authentic HTTP/issuer/browser path."""
import json
import unittest
from unittest.mock import patch

from test_guest_inventory_children_data import InventoryChildrenData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services import pilot_guest_inventory_children_data as children
from freq.services import pilot_guest_inventory_frame_data as source
from freq.services.guest_profile_formats.guest_owner_wire import project_guest_owner_wire


OBSERVED = '2026-10-24T01:02:03.004Z'
COMPLETED = '2026-10-24T01:02:04.005Z'


class InventoryFrameData(unittest.TestCase):
    def setUp(self):
        self.fixture = InventoryChildrenData()
        self.fixture.setUp()

    def duty(self, count=2):
        batch = self.fixture.batch(count)
        children.prepare_inventory_guest_records_data(batch,self.fixture.keys(count))
        return source._InventoryFramePreparationData(batch,OBSERVED,COMPLETED)

    def body(self, duty):
        return duty.frame._wire.split(b'\r\n\r\n',1)[1]

    def test_IF01_canonical_whole_v2_body_same_family_source_rows_and_refs(self):
        duty = self.duty()
        source.prepare_inventory_frame_data(duty)
        value = {'schema':2,'kind':'guest-inventory','owner_ref':'b'*64,
            'source_label':'fixture-label','observed_at':OBSERVED,'completed_at':COMPLETED,
            'guests':[dict(guest_ref=format(i+1,'064x'),node='fixture-node',
                guest_kind='qemu'if i%2==0 else'lxc',vmid=100+i,name='fixture-'+str(i))
                for i in range(2)]}
        self.assertEqual(self.body(duty),project_guest_owner_wire(value))
        self.assertEqual(json.loads(self.body(duty)),value)
        self.assertEqual(duty.phase,'prepared')
        self.assertEqual(duty.end,115.0)
        self.assertEqual(duty.batch.ticket._state,'reserved')

    def test_IF02_original_headers_exact_length_no_store_charset_close_and_CSP(self):
        duty = self.duty()
        source.prepare_inventory_frame_data(duty)
        header,body = duty.frame._wire.split(b'\r\n\r\n',1)
        self.assertTrue(header.startswith(b'HTTP/1.1 200 OK\r\n'))
        self.assertIn(b'Content-Type: application/json; charset=utf-8\r\n',header)
        self.assertIn(b'Content-Length: '+str(len(body)).encode('ascii')+b'\r\n',header)
        self.assertIn(b'Cache-Control: no-store\r\n',header)
        self.assertIn(b'Connection: close\r\n',header)
        self.assertIn(b'Content-Security-Policy:',header)
        self.assertNotIn(b'Transfer-Encoding:',header)
        self.assertNotIn(b'Content-Encoding:',header)

    def test_IF03_empty_guest_frame_does_not_settle_explicit_zero_ticket(self):
        duty = self.duty(0)
        source.prepare_inventory_frame_data(duty)
        self.assertEqual(json.loads(self.body(duty))['guests'],[])
        self.assertEqual(duty.batch.ticket._remaining,0)
        self.assertEqual(duty.batch.ticket._state,'reserved')
        capacity = self.fixture.fixture.owner._guest_capacity
        self.assertIs(capacity._tickets[id(duty.batch.ticket)],duty.batch.ticket)

    def test_IF04_completed_timestamp_does_not_renew_original_end_or_imply_order(self):
        duty = self.duty()
        duty.observed_at,duty.completed_at = COMPLETED,OBSERVED
        source.prepare_inventory_frame_data(duty)
        self.assertEqual(duty.end,115.0)
        self.assertEqual(duty.begin.end,115.0)
        self.assertEqual(json.loads(self.body(duty))['completed_at'],OBSERVED)

    def test_IF05_invalid_display_stamp_refuses_with_no_frame_and_no_retry(self):
        duty = self.duty()
        duty.completed_at = '2026-02-30T01:02:03.004Z'
        with self.assertRaises(ValueError): source.prepare_inventory_frame_data(duty)
        self.assertEqual(duty.phase,'format-attempted')
        self.assertIsNone(duty.frame)
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)

    def test_IF06_aggregate_string_overflow_refuses_whole_256_not_partial_rows(self):
        f = self.fixture.fixture
        raw = json.dumps({'data':[dict(type='qemu',node='n',vmid=100+i,name='x'*256)
            for i in range(256)]},separators=(',',':')).encode('utf-8')
        decoded = children._DecodedGuestRowsData(raw)
        ticket = f.owner._guest_capacity._reserve(f.session,f.values[0],256)
        batch = children._InventoryGuestBatchData(self.fixture.begin,decoded,ticket,111.0)
        children.prepare_inventory_guest_records_data(batch,self.fixture.keys(256))
        duty = source._InventoryFramePreparationData(batch,OBSERVED,COMPLETED)
        with self.assertRaises(ValueError): source.prepare_inventory_frame_data(duty)
        self.assertIsNone(duty.frame)
        self.assertEqual(len(batch.records),256)
        self.assertEqual(batch.ticket._remaining,256)
        self.assertEqual(batch.ticket._state,'reserved')

    def test_IF07_equal_reconstructed_target_cannot_create_frame(self):
        duty = self.duty()
        record = duty.batch.records[0]
        record._target = tuple(list(record._target))
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)
        self.assertIsNone(duty.frame)

    def test_IF08_retired_private_child_cannot_be_formatted_as_live(self):
        duty = self.duty()
        duty.batch.records[1]._retire()
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)
        self.assertIsNone(duty.frame)

    def test_IF09_repeated_format_refuses_preserving_exact_immutable_frame(self):
        duty = self.duty()
        source.prepare_inventory_frame_data(duty)
        saved = duty.frame
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)
        self.assertIs(duty.frame,saved)
        with self.assertRaises(TypeError): saved._wire = b'changed'

    def test_IF10_foreign_family_ref_cannot_replace_prepared_family(self):
        duty = self.duty()
        duty.begin.family_ref = 'd'*64
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)
        self.assertIsNone(duty.frame)

    def test_IF11_unknown_original_frame_constructor_return_cannot_retry(self):
        duty = self.duty()
        control = KeyboardInterrupt('fixture frame allocation return')
        with patch.object(source,'OriginalPilotResponse',side_effect=control):
            with self.assertRaises(KeyboardInterrupt) as caught:
                source.prepare_inventory_frame_data(duty)
        self.assertIs(caught.exception,control)
        self.assertEqual(duty.phase,'format-attempted')
        self.assertIsNone(duty.frame)
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(duty)

    def test_IF12_foreign_duty_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self,name): raise AssertionError('foreign frame hook')
        with self.assertRaises(_RequestUnavailable): source.prepare_inventory_frame_data(Trap())
