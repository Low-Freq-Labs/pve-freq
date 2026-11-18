"""Proposed wire-format DATA checks; no original response or source authority."""
import hashlib
import json
import unittest
from unittest.mock import patch

from freq.services import pilot_fleet_targets_wire as wire
from freq.services.pilot_fleet_targets_data import (
    ConfiguredFleetTargetsData, FleetTargetDataUnavailable,
    decode_fleet_target_bytes,
)


class FleetTargetsWireData(unittest.TestCase):
    def data(self, pairs):
        digest = hashlib.sha256(json.dumps(sorted(pairs), ensure_ascii=True,
            separators=(',', ':')).encode('ascii')).hexdigest()
        return ConfiguredFleetTargetsData(pairs, digest)

    def refused(self, data):
        with self.assertRaises(FleetTargetDataUnavailable) as caught:
            wire.format_retained_fleet_targets_data(data)
        self.assertEqual(str(caught.exception), 'Configured Fleet target data unavailable')

    def test_FW01_exact_truthful_fixed_metadata_and_complete_unicode_rows(self):
        data = decode_fleet_target_bytes(
            '[[host]]\nlabel="fixture-é"\nip="192.0.2.3"'.encode())
        body = wire.format_retained_fleet_targets_data(data)
        self.assertTrue(body.isascii())
        expected = dict(schema='fleet-exec-targets-v2', ok=True,
            source='retained_hosts_bytes', scope='configured_host_pairs',
            complete=True, hosts=[{'label': 'fixture-é', 'ip': '192.0.2.3'}],
            target_set_sha256=data.target_set_sha256, raw_config_verified=False,
            loader_may_bootstrap_or_migrate=False, estate_complete=False,
            adoption_verified=False, reachability_verified=False)
        self.assertEqual(json.loads(body), expected)

    def test_FW02_explicit_empty_is_complete_with_real_empty_digest(self):
        data = decode_fleet_target_bytes(b'host=[]')
        doc = json.loads(wire.format_retained_fleet_targets_data(data))
        self.assertEqual(doc['hosts'], [])
        self.assertTrue(doc['complete'])
        self.assertEqual(doc['target_set_sha256'], hashlib.sha256(b'[]').hexdigest())

    def test_FW03_foreign_type_refuses_before_attribute_hooks(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute hook')
        self.refused(Hostile())

    def test_FW04_mutable_pair_collection_cannot_be_serialized(self):
        self.refused(ConfiguredFleetTargetsData([('a', 'b')], '0' * 64))

    def test_FW05_late_bad_row_never_returns_a_valid_prefix(self):
        self.refused(ConfiguredFleetTargetsData((('a', 'b'), ('last',)), '0' * 64))

    def test_FW06_cross_row_alias_collision_refuses_whole_collection(self):
        self.refused(self.data((('a', 'b'), ('b', 'c'))))

    def test_FW07_same_row_label_address_alias_is_preserved(self):
        doc = json.loads(wire.format_retained_fleet_targets_data(self.data((('a', 'a'),))))
        self.assertEqual(doc['hosts'], [{'label': 'a', 'ip': 'a'}])

    def test_FW08_wrong_or_noncanonical_digest_cannot_be_trusted(self):
        for value in ('0' * 64, 'A' * 64, 'short', None, True):
            with self.subTest(value=value):
                self.refused(ConfiguredFleetTargetsData((('a', 'b'),), value))

    def test_FW09_invalid_unicode_refuses_with_only_fixed_error_text(self):
        self.refused(ConfiguredFleetTargetsData((('private\ud800', 'b'),), '0' * 64))

    def test_FW10_pair_count_above_cap_refuses_before_hash(self):
        data = ConfiguredFleetTargetsData(tuple(('a', 'b') for _ in range(1001)), '0' * 64)
        with patch.object(wire.hashlib, 'sha256', side_effect=AssertionError('hash after count refusal')):
            self.refused(data)

    def test_FW11_utf8_identity_byte_boundary_is_independent_of_codepoint_count(self):
        valid = self.data((('é' * 128, 'b'),))
        self.assertEqual(json.loads(wire.format_retained_fleet_targets_data(valid))['hosts'][0]['label'], 'é' * 128)
        self.refused(self.data((('é' * 128 + 'a', 'b'),)))

    def test_FW12_c0_del_refuse_while_historical_c1_and_format_rule_is_preserved(self):
        for value in ('a\tb', 'a\x00b', 'a\x7fb'):
            with self.subTest(value=value):
                self.refused(self.data(((value, 'endpoint'),)))
        value = 'a\x85\u200db'
        doc = json.loads(wire.format_retained_fleet_targets_data(self.data(((value, 'endpoint'),))))
        self.assertEqual(doc['hosts'][0]['label'], value)

    def test_FW13_configured_order_is_preserved_with_order_independent_digest(self):
        pairs = (('z', '192.0.2.2'), ('a', '192.0.2.1'))
        first, other = self.data(pairs), self.data(tuple(reversed(pairs)))
        self.assertEqual(first.target_set_sha256, other.target_set_sha256)
        doc = json.loads(wire.format_retained_fleet_targets_data(first))
        self.assertEqual(tuple((r['label'], r['ip']) for r in doc['hosts']), pairs)

    def test_FW14_unknown_allocation_and_control_errors_never_produce_data(self):
        for error in (MemoryError('fixture'), KeyboardInterrupt('fixture')):
            with self.subTest(kind=type(error).__name__), patch.object(
                    wire.hashlib, 'sha256', side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    wire.format_retained_fleet_targets_data(
                        ConfiguredFleetTargetsData((('a', 'b'),), '0' * 64))
                self.assertIs(caught.exception, error)

    def test_FW15_serialization_never_mutates_private_projection(self):
        data = self.data((('a', 'b'),))
        before = data.pairs, data.target_set_sha256
        wire.format_retained_fleet_targets_data(data)
        self.assertIs(data.pairs, before[0])
        self.assertIs(data.target_set_sha256, before[1])

    def test_FW16_output_cap_exact_boundary_and_no_truncated_prefix(self):
        data = self.data((('a', 'b'),))
        body = wire.format_retained_fleet_targets_data(data)
        with patch.object(wire, 'TARGET_WIRE_LIMIT', len(body)):
            self.assertEqual(wire.format_retained_fleet_targets_data(data), body)
        with patch.object(wire, 'TARGET_WIRE_LIMIT', len(body) - 1):
            self.refused(data)

    def test_FW17_maximum_row_count_and_escaped_byte_budget_fit_logical_wire_cap(self):
        pairs = tuple((f'a{i:04d}' + '\x85' * 125 + 'x',
                       f'b{i:04d}' + '\x86' * 125 + 'y') for i in range(1000))
        body = wire.format_retained_fleet_targets_data(self.data(pairs))
        self.assertLessEqual(len(body), wire.TARGET_WIRE_LIMIT)
        self.assertEqual(len(json.loads(body)['hosts']), 1000)

    def test_FW18_foreign_pair_member_refuses_before_conversion_or_equality(self):
        class Hostile:
            def __str__(self):
                raise AssertionError('foreign string conversion')
            def __eq__(self, other):
                raise AssertionError('foreign equality')
        self.refused(ConfiguredFleetTargetsData(((Hostile(), 'b'),), '0' * 64))
