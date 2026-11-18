"""Fictional status decoder cases; no provider requests or authority inputs."""

import json
import unittest

from freq.services.guest_profile_formats.guest_status import Refused, decode_guest_status


def body(value):
    return json.dumps({"data": value}, ensure_ascii=False,
                      separators=(",", ":")).encode()


class StatusTests(unittest.TestCase):
    def refused(self, raw):
        with self.assertRaises(Refused) as caught:
            decode_guest_status(raw)
        self.assertEqual(str(caught.exception), "Guest status unavailable")

    def test_GS01_four_display_values_only(self):
        value = {"status": "running", "cpu": 0.25, "mem": 1048576, "maxmem": 2097152,
                 "vmid": 120, "name": "discarded", "qmpstatus": "paused"}
        self.assertEqual(decode_guest_status(body(value)),
                         {"state": "running", "cpu_fraction": 0.25,
                          "memory_used_bytes": 1048576, "memory_limit_bytes": 2097152})

    def test_GS02_absent_optional_values_are_null(self):
        self.assertEqual(decode_guest_status(body({"status": "stopped"})),
                         {"state": "stopped", "cpu_fraction": None,
                          "memory_used_bytes": None, "memory_limit_bytes": None})

    def test_GS03_cpu_boundaries_and_exponents(self):
        for raw, expected in ((b"0", 0.0), (b"-0", 0.0), (b"1", 1.0),
                              (b"1e-1", 0.1), (b"1.000e0", 1.0), (b"1e-300", 1e-300)):
            value = decode_guest_status(b'{"data":{"status":"running","cpu":' + raw + b'}}')
            self.assertEqual(value["cpu_fraction"], expected)

    def test_GS04_cpu_exact_range_before_rounding(self):
        for raw in (b"-1e-999", b"1.00000000000000000000000000000000001", b"2",
                    b"1e999999", b"1e-999", b"NaN", b"Infinity", b"-Infinity"):
            self.refused(b'{"data":{"status":"running","cpu":' + raw + b'}}')

    def test_GS05_cpu_malformed_present_is_not_absent(self):
        for value in (None, True, "0", [], {}):
            self.refused(body({"status": "running", "cpu": value}))

    def test_GS06_memory_unsigned_53_bit_edges(self):
        for value in (0, 9007199254740991):
            result = decode_guest_status(body({"status": "running", "mem": value, "maxmem": value}))
            self.assertEqual(result["memory_used_bytes"], value)
            self.assertIs(type(result["memory_used_bytes"]), int)
        for key in ("mem", "maxmem"):
            for value in (-1, 9007199254740992, True, None, "1", 1.0, [], {}):
                self.refused(body({"status": "running", key: value}))

    def test_GS07_memory_lexemes_before_conversion(self):
        for raw in (b"-0", b"01", b"1e0", b"0.0", b"1" * 64, b"1" * 65):
            self.refused(b'{"data":{"status":"running","mem":' + raw + b'}}')

    def test_GS08_status_literal_and_utf8_bound(self):
        for state in ("custom", "é" * 32, "<b>literal</b>\n"):
            self.assertEqual(decode_guest_status(body({"status": state}))["state"], state)
        for state in ("", "é" * 33, None, 1, True, [], {}):
            self.refused(body({"status": state}))

    def test_GS09_exact_transport_wrapper_and_required_status(self):
        for raw in (b"[]", b'{"status":"running"}', b'{"data":{}}', b'{"data":null}',
                    b'{"data":[]}', b'{"data":{"status":"running"},"extra":0}'):
            self.refused(raw)

    def test_GS10_known_ha_flat_object_discarded(self):
        for ha in ({}, {"managed": 0}, {"managed": 1, "state": "started", "flag": True, "x": None}):
            result = decode_guest_status(body({"status": "running", "ha": ha}))
            self.assertEqual(set(result), {"state", "cpu_fraction", "memory_used_bytes", "memory_limit_bytes"})
        for ha in (None, True, "managed", [], {"nested": {}}, {"nested": []}):
            self.refused(body({"status": "running", "ha": ha}))

    def test_GS11_unknown_scalars_only_and_no_statistics_forwarding(self):
        value = {"status": "running", "discard": "x" * 4096, "other": None, "cpu_time": 123}
        self.assertEqual(set(decode_guest_status(body(value))),
                         {"state", "cpu_fraction", "memory_used_bytes", "memory_limit_bytes"})
        for extra in ([], {}):
            self.refused(body({"status": "running", "unknown": extra}))
        self.refused(body({"status": "running", "discard": "x" * 4097}))

    def test_GS12_duplicate_keys_and_ascii_before_discard(self):
        for raw in (b'{"data":{"status":"running","status":"stopped"}}',
                    b'{"data":{"status":"running","x":0,"\\u0078":1}}',
                    b'{"data":{"status":"running","ha":{"x":0,"x":1}}}',
                    b'{"data":{"status":"running","\\u00e9":1}}'):
            self.refused(raw)

    def test_GS13_utf8_bom_and_surrogates(self):
        for raw in (b"\xff", b"\xef\xbb\xbf" + body({"status": "running"}),
                    b'{"data":{"status":"\\ud800"}}', b'{"data":{"status":"\\udc00"}}'):
            self.refused(raw)
        self.assertEqual(decode_guest_status(b'{"data":{"status":"\\ud83d\\ude00"}}')["state"], "😀")

    def test_GS14_raw_cap_trailing_and_exact_bytes(self):
        raw = body({"status": "running"})
        self.assertEqual(decode_guest_status(raw + b" " * (262144 - len(raw)))["state"], "running")
        self.refused(raw + b" " * (262145 - len(raw)))
        for bad in (raw + b"{}", raw + b"\x00", bytearray(raw), memoryview(raw)):
            self.refused(bad)

    def test_GS15_global_decoded_strings_include_keys(self):
        # 15*4096 plus one adjusted value consumes exactly 65536 bytes,
        # including root key, status key/value and the sixteen extension keys.
        value = {"status": "r"}
        value.update({"k" + str(i): "x" * 4096 for i in range(15)})
        overhead = len("data") + sum(len(k) for k in value) + len("r") + len("tail")
        value["tail"] = "y" * (65536 - 15 * 4096 - overhead)
        self.assertEqual(decode_guest_status(body(value))["state"], "r")
        value["tail"] += "y"
        self.refused(body(value))

    def test_GS16_known_container_member_bound(self):
        ha = {"k" + str(i): None for i in range(128)}
        self.assertEqual(decode_guest_status(body({"status": "running", "ha": ha}))["state"], "running")
        ha["extra"] = None
        self.refused(body({"status": "running", "ha": ha}))

    def test_GS17_unknown_numeric_lexeme_charged_not_converted(self):
        prefix = b'{"data":{"status":"running","unused":'
        self.assertEqual(decode_guest_status(prefix + b"9" * 64 + b'}}')["state"], "running")
        self.refused(prefix + b"9" * 65 + b'}}')
        self.refused(prefix + b"1e" + b"9" * 63 + b'}}')

    def test_GS18_results_are_independent_no_target_or_time(self):
        raw = body({"status": "running", "mem": 5, "maxmem": 1})
        first = decode_guest_status(raw)
        first["state"] = "modified"
        second = decode_guest_status(raw)
        self.assertEqual(second["state"], "running")
        # Report both literal memory figures; do not infer health or clamp.
        self.assertEqual((second["memory_used_bytes"], second["memory_limit_bytes"]), (5, 1))
        self.assertEqual(set(second), {"state", "cpu_fraction", "memory_used_bytes", "memory_limit_bytes"})


    def test_GS19_genuine_native_payload_with_explicit_adapter_wrapper(self):
        # This is an actual pvesh JSON result, not captured HTTP response bytes.
        # The required application transport envelope is added by this fixture.
        from pathlib import Path
        native = Path(__file__).with_name('branch-status-native.json').read_bytes()
        result = decode_guest_status(b'{"data":' + native.strip() + b'}')
        self.assertEqual(result, {'state': 'running', 'cpu_fraction': 0.0,
            'memory_used_bytes': 1103286272, 'memory_limit_bytes': 1073741824})

    def test_GS20_only_three_known_metadata_objects_are_discarded(self):
        for key in ('blockstat', 'nics', 'proxmox-support'):
            for metadata in ({}, {'nested': {'values': [0, True, None, 'text']}}):
                result = decode_guest_status(body({'status': 'running', key: metadata}))
                self.assertEqual(result, {'state': 'running', 'cpu_fraction': None,
                    'memory_used_bytes': None, 'memory_limit_bytes': None})

    def test_GS21_known_metadata_must_be_builtin_JSON_object(self):
        for key in ('blockstat', 'nics', 'proxmox-support'):
            for metadata in (None, [], 0, True, 'x'):
                self.refused(body({'status': 'running', key: metadata}))

    def test_GS22_other_unknown_containers_still_refuse(self):
        for value in ({}, []):
            self.refused(body({'status': 'running', 'blockstat': {}, 'other': value}))
        self.assertEqual(decode_guest_status(body({'status': 'running',
                         'blockstat': {}, 'other': 'discarded'}))['state'], 'running')

    def test_GS23_metadata_duplicates_ASCII_and_numeric_caps_before_discard(self):
        for raw in (
            b'{"data":{"status":"running","blockstat":{"x":0,"\\u0078":1}}}',
            b'{"data":{"status":"running","nics":{"\\u00e9":0}}}',
            b'{"data":{"status":"running","proxmox-support":{"x":NaN}}}',
            b'{"data":{"status":"running","blockstat":{"x":' + b'9'*65 + b'}}}',
        ):
            self.refused(raw)

    def test_GS24_metadata_object_and_depth_limits_are_not_bypassed(self):
        metadata = {'k'+str(i): None for i in range(128)}
        self.assertEqual(decode_guest_status(body({'status':'r','blockstat':metadata}))['state'], 'r')
        metadata['overflow'] = None
        self.refused(body({'status':'r','blockstat':metadata}))
        nested = {}
        for _ in range(3):
            nested = {'x': nested}
        self.assertEqual(decode_guest_status(body({'status':'r','nics':nested}))['state'], 'r')
        self.refused(body({'status':'r','nics':{'x':nested}}))

    def test_GS25_discarded_metadata_still_charges_aggregate_string_bytes(self):
        metadata = {'k'+str(i): 'x'*4096 for i in range(15)}
        overhead = len('data')+len('status')+len('r')+len('blockstat')
        overhead += sum(len(k)for k in metadata)+len('tail')
        metadata['tail'] = 'y'*(65536-15*4096-overhead)
        self.assertEqual(decode_guest_status(body({'status':'r','blockstat':metadata}))['state'], 'r')
        metadata['tail'] += 'y'
        self.refused(body({'status':'r','blockstat':metadata}))


if __name__ == "__main__":
    unittest.main()
