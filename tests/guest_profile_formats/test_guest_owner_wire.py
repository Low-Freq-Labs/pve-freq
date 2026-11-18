"""Future DATA fixtures only. No original owner, provider call or ACK proof."""
import copy
import json
import unittest

from freq.services.guest_profile_formats.guest_owner_wire import project_guest_owner_wire
from freq.services.guest_profile_formats.guest_wire import Refused
from freq.services.guest_profile_formats.guest_config import decode_guest_config
from freq.services.guest_profile_formats.guest_status import decode_guest_status
from freq.services.guest_profile_formats.guest_network import decode_guest_network
from freq.services.guest_profile_formats.guest_inventory import decode_guest_inventory


STAMP = '2026-10-24T10:11:10.000Z'
FAMILY = 'a' * 64


def section(outcome='unavailable', data=None):
    return dict(outcome=outcome, observed_at=STAMP if outcome == 'reported' else None,
                data=data)


def profile():
    return dict(schema=2, kind='guest-profile', owner_ref=FAMILY,
                target=dict(source_label='Branch', node='branch-pve',
                            guest_kind='qemu', vmid=120, name='branch-test-vm'),
                completed_at=STAMP, status=section(),
                configured_network=section(), guest_network=section())


def inventory(count=256, name=''):
    return dict(schema=2, kind='guest-inventory', owner_ref=FAMILY,
                source_label='Branch', observed_at=STAMP, completed_at=STAMP,
                guests=[dict(guest_ref=format(i, '064x'), node='branch-pve',
                             guest_kind='qemu', vmid=100+i, name=name)
                        for i in range(count)])


def string_bytes(value):
    if type(value) is str:
        return len(value.encode('utf-8'))
    if type(value) is dict:
        return sum(len(key.encode('utf-8')) + string_bytes(child)
                   for key, child in value.items())
    if type(value) is list:
        return sum(string_bytes(child) for child in value)
    return 0


class OwnerWireTests(unittest.TestCase):
    def refused(self, value):
        with self.assertRaises(Refused):
            project_guest_owner_wire(value)

    def test_OW01_three_exact_success_shapes_roundtrip(self):
        sources = dict(schema=2, kind='guest-sources', owner_ref=FAMILY,
                       sources=[dict(source_ref='b'*64, label='Branch')], completed_at=STAMP)
        for value in (sources, inventory(1), profile()):
            self.assertEqual(json.loads(project_guest_owner_wire(value)), value)

    def test_OW02_schema_two_only_not_bool_float_or_one(self):
        for schema in (1, True, 2.0, '2', None):
            value = profile(); value['schema'] = schema
            self.refused(value)

    def test_OW03_owner_reference_shape_not_authority(self):
        for family in (None, 4, b'a'*64, 'a'*63, 'a'*65, 'A'*64, 'g'*64):
            value = profile(); value['owner_ref'] = family
            self.refused(value)
        value = profile(); value['owner_ref'] = '0'*64
        self.assertEqual(json.loads(project_guest_owner_wire(value))['owner_ref'], '0'*64)

    def test_OW04_every_root_field_required_extra_refuses(self):
        for key in profile():
            value = profile(); del value[key]
            self.refused(value)
        value = profile(); value['authority'] = True
        self.refused(value)

    def test_OW05_builtin_root_keys_and_reference_no_hooks(self):
        class ForeignDict(dict):
            def items(self):
                raise AssertionError('foreign mapping hook called')
        class ForeignText(str):
            def encode(self, *args):
                raise AssertionError('foreign string hook called')
        self.refused(ForeignDict(profile()))
        value = profile(); value['owner_ref'] = ForeignText(FAMILY)
        self.refused(value)
        value = profile(); value[ForeignText('owner_ref')] = value.pop('owner_ref')
        self.refused(value)

    def test_OW06_fixed_frame_kinds_are_not_success_projection(self):
        for value in (dict(schema=2, kind='guest-owner', owner_ref=FAMILY, completed_at=STAMP),
                      dict(schema=2, kind='guest-owner-retired', open_nonce=FAMILY),
                      dict(schema=2, kind='guest-unavailable')):
            self.refused(value)

    def test_OW07_family_is_not_added_to_nested_target(self):
        value = profile(); value['target']['owner_ref'] = FAMILY
        self.refused(value)

    def test_OW08_independent_memory_bounds_no_clamp(self):
        value = profile()
        value['status'] = section('reported', dict(state='running', cpu_fraction=0,
            memory_used_bytes=1103286272, memory_limit_bytes=1073741824))
        self.assertEqual(json.loads(project_guest_owner_wire(value))['status'], value['status'])
        for field in ('memory_used_bytes', 'memory_limit_bytes'):
            changed = copy.deepcopy(value); changed['status']['data'][field] = 9007199254740992
            self.refused(changed)

    def test_OW09_malformed_late_section_suppresses_whole(self):
        value = profile(); value['guest_network'] = section('reported', [
            dict(name='eth0', mac=None, addresses=[]), dict(name='', mac=None, addresses=[])])
        self.refused(value)

    def test_OW10_lxc_remains_only_unsupported(self):
        value = profile(); value['target']['guest_kind'] = 'lxc'
        for key in ('status', 'configured_network', 'guest_network'):
            value[key] = section('unsupported')
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)
        value['status'] = section()
        self.refused(value)

    def test_OW11_inventory_uniqueness_and_257_neighbor(self):
        self.assertEqual(len(json.loads(project_guest_owner_wire(inventory()))['guests']), 256)
        self.refused(inventory(257))
        value = inventory(2); value['guests'][1]['guest_ref'] = value['guests'][0]['guest_ref']
        self.refused(value)
        value = inventory(2); value['guests'][1]['vmid'] = value['guests'][0]['vmid']
        self.refused(value)

    def test_OW12_family_key_and_value_inside_65536_budget(self):
        value = inventory()
        remaining = 65536 - string_bytes(value)
        self.assertGreater(remaining, 0)
        for row in value['guests']:
            size = min(remaining, 256)
            row['name'] = 'x' * size; remaining -= size
        self.assertEqual(remaining, 0)
        self.assertEqual(string_bytes(value), 65536)
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)
        next(row for row in value['guests'] if len(row['name']) < 256)['name'] += 'x'
        self.assertEqual(string_bytes(value), 65537)
        self.refused(value)

    def test_OW13_escaped_output_cap_independent_of_decoded_budget(self):
        value = inventory(name='\x00'*120)
        self.assertLess(string_bytes(value), 65536)
        self.assertGreater(len(json.dumps(value, ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')), 131072)
        self.refused(value)

    def test_OW14_canonical_immutable_snapshot_no_input_rewrite(self):
        value = profile(); value['target']['name'] = '<img src=x onerror="bad()">'
        original = copy.deepcopy(value)
        encoded = project_guest_owner_wire(value)
        self.assertIs(type(encoded), bytes)
        self.assertEqual(value, original)
        self.assertEqual(encoded, json.dumps(original, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(',', ':')).encode('utf-8'))
        value['target']['name'] = 'changed'
        self.assertEqual(json.loads(encoded), original)

    def test_OW15_packaged_config_status_agent_values_compose(self):
        value = profile()
        value['configured_network'] = section('reported', decode_guest_config(
            b'{"data":{"net0":"virtio=BC:24:11:28:06:DB,bridge=vmbr1,tag=7",'
            b'"ipconfig0":"ip=172.23.7.30/24,gw=172.23.7.1"}}'))
        value['status'] = section('reported', decode_guest_status(
            b'{"data":{"status":"running","cpu":0,"mem":1103286272,'
            b'"maxmem":1073741824,"nics":{"x":{"counter":1}}}}'))
        value['guest_network'] = section('reported', decode_guest_network(
            b'{"data":{"result":[{"name":"eth0","hardware-address":"bc:24:11:28:06:db",'
            b'"ip-addresses":[{"ip-address-type":"ipv4","ip-address":"172.23.7.30","prefix":24}]}]}}'))
        decoded = json.loads(project_guest_owner_wire(value))
        self.assertEqual(decoded, value)
        self.assertEqual(decoded['configured_network']['data'][0]['mac'], 'BC:24:11:28:06:DB')
        self.assertEqual(decoded['guest_network']['data'][0]['mac'], 'bc:24:11:28:06:db')
        self.assertNotIn('association', decoded)

    def test_OW16_packaged_inventory_does_not_issue_refs(self):
        selected = decode_guest_inventory(b'{"data":[{"type":"qemu","node":"branch-pve",'
            b'"vmid":120,"name":"branch-test-vm"}]}')
        self.assertEqual(selected, [dict(node='branch-pve', guest_kind='qemu',
            vmid=120, name='branch-test-vm')])
        value = inventory(0); value['guests'] = selected
        self.refused(value)
        # Explicit supplied DATA below is not an entropy or original issuer.
        selected[0]['guest_ref'] = 'b'*64
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)

    def test_OW17_unicode_literal_and_surrogate_refusal(self):
        value = profile(); value['target']['name'] = 'Branch 🛰'
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)
        value['target']['name'] = '\ud800'
        self.refused(value)

    def test_OW18_section_time_and_outcome_remain_explicit(self):
        value = profile(); value['status']['observed_at'] = STAMP
        self.refused(value)
        value = profile(); value['status']['outcome'] = 'empty'
        self.refused(value)
        value = profile(); value['guest_network'] = section('reported', [])
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)

    def test_OW19_source_empty_duplicate_and_bound(self):
        value = dict(schema=2, kind='guest-sources', owner_ref=FAMILY,
                     sources=[], completed_at=STAMP)
        self.assertEqual(json.loads(project_guest_owner_wire(value)), value)
        value['sources'] = [dict(source_ref=format(i, '064x'), label='Branch') for i in range(32)]
        self.assertEqual(len(json.loads(project_guest_owner_wire(value))['sources']), 32)
        value['sources'].append(dict(source_ref='b'*64, label='Other'))
        self.refused(value)
        value['sources'] = [dict(source_ref='b'*64, label='A'), dict(source_ref='b'*64, label='B')]
        self.refused(value)

    def test_OW20_completed_timestamp_calendar_and_field_types(self):
        for stamp in ('2026-02-29T00:00:00.000Z', '2026-10-24T10:11:10Z', None):
            value = profile(); value['completed_at'] = stamp
            self.refused(value)
        for vmid in (True, 120.0, 99, 1000000000):
            value = profile(); value['target']['vmid'] = vmid
            self.refused(value)
