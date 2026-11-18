"""Fictional retained-byte cases, no actual configuration or transport."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import unittest
from unittest.mock import patch

from freq.services.pilot_fleet_targets_data import (
    ConfiguredFleetTargetsData, FleetTargetDataUnavailable,
    HOSTS_BYTE_LIMIT, decode_fleet_target_bytes,
)


def document(pairs):
    return ''.join('[[host]]\nlabel=' + json.dumps(label, ensure_ascii=False) +
                   '\nip=' + json.dumps(address, ensure_ascii=False) + '\n'
                   for label, address in pairs).encode()


class PassiveFleetTargets(unittest.TestCase):
    def refuse(self, raw):
        with self.assertRaisesRegex(FleetTargetDataUnavailable,
                                    '^Configured Fleet target data unavailable$'):
            decode_fleet_target_bytes(raw)

    def test_PF01_configured_order_and_literal_identity(self):
        pairs = [('nas', '192.0.2.2'), ('pve', '2001:db8::1')]
        result = decode_fleet_target_bytes(document(pairs))
        self.assertEqual(result.pairs, tuple(pairs))

    def test_PF02_digest_matches_historical_target_set_correlation(self):
        pairs = [('z', '192.0.2.2'), ('a', '192.0.2.1')]
        a = decode_fleet_target_bytes(document(pairs))
        b = decode_fleet_target_bytes(document(list(reversed(pairs))))
        expected = hashlib.sha256(json.dumps(sorted(pairs), ensure_ascii=True,
                    separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(a.target_set_sha256, expected)
        self.assertEqual(a.target_set_sha256, b.target_set_sha256)
        self.assertNotEqual(a.pairs, b.pairs)

    def test_PF03_explicit_empty_is_distinct_from_missing(self):
        result = decode_fleet_target_bytes(b'host=[]\n')
        self.assertEqual(result.pairs, ())
        for raw in (None, b'', b'# only a comment\n', b'[other]\nx=1\n'):
            with self.subTest(raw=raw):
                self.refuse(raw)

    def test_PF04_late_invalid_row_never_returns_valid_prefix(self):
        self.refuse(document([('valid', '192.0.2.1')]) + b'[[host]]\nlabel="bad"\n')

    def test_PF05_duplicate_and_cross_aliases_refuse_whole_set(self):
        for pairs in ([('a', '192.0.2.1'), ('a', '192.0.2.2')],
                      [('a', '192.0.2.1'), ('b', '192.0.2.1')],
                      [('a', '192.0.2.1'), ('192.0.2.1', '192.0.2.2')],
                      [('a', '192.0.2.1'), ('b', 'a')]):
            with self.subTest(pairs=pairs):
                self.refuse(document(pairs))

    def test_PF06_same_row_label_address_alias_is_supported(self):
        self.assertEqual(decode_fleet_target_bytes(document([('same', 'same')])).pairs,
                         (('same', 'same'),))

    def test_PF07_thousand_targets_and_whole_overflow(self):
        pairs = [(f'node{i}', f'192.0.2.{i}') for i in range(1000)]
        self.assertEqual(len(decode_fleet_target_bytes(document(pairs)).pairs), 1000)
        self.refuse(document(pairs + [('last', '203.0.113.1')]))

    def test_PF08_exact_byte_cap_and_overflow(self):
        raw = b'host=[]\n#' + b'x' * (HOSTS_BYTE_LIMIT - 9)
        self.assertEqual(len(raw), HOSTS_BYTE_LIMIT)
        self.assertEqual(decode_fleet_target_bytes(raw).pairs, ())
        self.refuse(raw + b'x')

    def test_PF09_utf8_identity_byte_limit_not_character_limit(self):
        label = 'é' * 128
        self.assertEqual(decode_fleet_target_bytes(document([(label, 'a')])).pairs,
                         ((label, 'a'),))
        self.refuse(document([(label + 'é', 'a')]))

    def test_PF10_whitespace_controls_and_empty_are_not_repaired(self):
        for value in ('', ' leading', 'trailing ', 'line\nbreak', '\x7f', '\x00'):
            with self.subTest(value=value):
                self.refuse(document([(value, '192.0.2.1')]))

    def test_PF11_types_and_missing_fields_refuse(self):
        for raw in (b'host={label="a",ip="b"}', b'host=[1]',
                    b'[[host]]\nlabel=1\nip="a"',
                    b'[[host]]\nlabel="a"\nip=true',
                    b'[[host]]\nip="a"'):
            with self.subTest(raw=raw):
                self.refuse(raw)

    def test_PF12_malformed_or_duplicate_TOML_and_utf8_refuse(self):
        for raw in (b'host=[', b'host=[]\nhost=[]', b'\xff',
                    b'[[host]]\nlabel="a"\nlabel="b"\nip="c"'):
            with self.subTest(raw=raw):
                self.refuse(raw)

    def test_PF13_metadata_does_not_expand_or_select_targets(self):
        raw = (b'[[host]]\nlabel="literal"\nip="192.0.2.1"\n'
               b'groups="all,prod"\nmanaged=false\n'
               b'all_ips=["192.0.2.2"]\nssh_user="someone"\n')
        self.assertEqual(decode_fleet_target_bytes(raw).pairs,
                         (('literal', '192.0.2.1'),))

    def test_PF14_exact_bytes_type_refuses_subclass_without_hooks(self):
        class Other(bytes):
            def decode(self, *a, **kw):
                raise AssertionError('subclass hook must not run')
        self.refuse(Other(b'host=[]'))
        self.refuse(bytearray(b'host=[]'))

    def test_PF15_control_and_allocation_propagate_without_default_result(self):
        for error in (KeyboardInterrupt(), MemoryError()):
            with self.subTest(error=type(error).__name__):
                with patch('freq.services.pilot_fleet_targets_data.tomllib.loads', side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        decode_fleet_target_bytes(b'host=[]')
                    self.assertIs(caught.exception, error)

    def test_PF16_parser_diagnostic_context_is_not_chained(self):
        try:
            decode_fleet_target_bytes(b'host=[')
        except FleetTargetDataUnavailable as error:
            self.assertIsNone(error.__context__)
            self.assertIsNone(error.__cause__)
        else:
            self.fail('malformed source was accepted')

    def test_PF17_result_is_immutable_data_without_payload_or_grant(self):
        result = decode_fleet_target_bytes(b'host=[]')
        self.assertIs(type(result), ConfiguredFleetTargetsData)
        with self.assertRaises(FrozenInstanceError):
            result.pairs = (('invented', 'invented'),)
        self.assertFalse(hasattr(result, '__dict__'))
        self.assertFalse(hasattr(result, 'current'))
        self.assertNotIn('pairs=', repr(result))
