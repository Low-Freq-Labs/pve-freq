"""Fictional finite cases only; source is unrun pending qualified execution."""

import copy
import json
import unittest

from freq.services.guest_profile_formats.guest_network import Reader, Refused, decode_guest_network


def encode(interfaces):
    return json.dumps({"data": {"result": interfaces}}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def interface():
    return {"name": "eth0", "hardware-address": "aa:bb:cc:dd:ee:ff",
            "ip-addresses": [{"ip-address": "192.0.2.1", "ip-address-type": "ipv4", "prefix": 24},
                             {"ip-address": "fe80::1", "ip-address-type": "ipv6", "prefix": 64}]}


def statistics():
    return {key: 0 for key in ("rx-bytes", "rx-packets", "rx-errs", "rx-dropped",
                               "tx-bytes", "tx-packets", "tx-errs", "tx-dropped")}


class NetworkTests(unittest.TestCase):
    def refused(self, body):
        with self.assertRaises(Refused) as ctx:
            decode_guest_network(body)
        self.assertEqual(str(ctx.exception), "Guest network unavailable")

    def test_GN01_two_families_and_stats_discard(self):
        value = interface()
        value["statistics"] = statistics()
        value["statistics"]["rx-bytes"] = 18446744073709551615
        result = decode_guest_network(encode([value]))
        self.assertEqual(result, [{"name": "eth0", "mac": "aa:bb:cc:dd:ee:ff",
                                  "addresses": [{"family": "ipv4", "address": "192.0.2.1", "prefix": 24},
                                                {"family": "ipv6", "address": "fe80::1", "prefix": 64}]}])
        self.assertNotIn("statistics", result[0])

    def test_GN02_empty_and_absent_optional(self):
        self.assertEqual(decode_guest_network(encode([])), [])
        self.assertEqual(decode_guest_network(encode([{"name": "lo"}])),
                         [{"name": "lo", "mac": None, "addresses": []}])

    def test_GN03_exact_wrappers(self):
        for body in (b'[]', b'{"result":[]}', b'{"data":[]}', b'{"data":{"result":[]},"extra":1}',
                     b'{"data":{"result":[],"extra":1}}', b'{"data":{"result":null}}'):
            self.refused(body)

    def test_GN04_duplicates_before_discard(self):
        for body in (b'{"data":{"result":[]},"data":{"result":[]}}',
                     b'{"data":{"result":[{"name":"lo","x":1,"x":2}]}}',
                     b'{"data":{"result":[{"name":"lo","n\\u0061me":"eth0"}]}}'):
            self.refused(body)

    def test_GN05_utf8_bom_surrogates_and_escape(self):
        for body in (b'\xef\xbb\xbf' + encode([]), b'\xff',
                     b'{"data":{"result":[{"name":"\\ud800"}]}}',
                     b'{"data":{"result":[{"name":"\\udc00"}]}}',
                     b'{"data":{"result":[{"name":"\\x00"}]}}'):
            self.refused(body)
        body = b'{"data":{"result":[{"name":"\\ud83d\\ude00"}]}}'
        self.assertEqual(decode_guest_network(body)[0]["name"], "😀")

    def test_GN06_literal_controls_and_hostile_name(self):
        value = {"name": '<script>bad()</script>\n', "hardware-address": "invalid-mac"}
        self.assertEqual(decode_guest_network(encode([value]))[0]["name"], value["name"])
        self.refused(b'{"data":{"result":[{"name":"bad\nname"}]}}')

    def test_GN07_interface_and_address_caps(self):
        self.assertEqual(len(decode_guest_network(encode([{"name": "lo"}] * 64))), 64)
        self.refused(encode([{"name": "lo"}] * 65))
        value = interface()
        value["ip-addresses"] = [value["ip-addresses"][0]] * 16
        self.assertEqual(len(decode_guest_network(encode([value]))[0]["addresses"]), 16)
        value["ip-addresses"].append(copy.deepcopy(value["ip-addresses"][0]))
        self.refused(encode([value]))

    def test_GN08_name_and_mac_utf8_bounds(self):
        value = {"name": "é" * 64, "hardware-address": "x" * 128}
        self.assertEqual(decode_guest_network(encode([value]))[0]["name"], value["name"])
        for field, bad in (("name", "é" * 65), ("name", ""), ("hardware-address", "x" * 129),
                           ("hardware-address", None), ("name", 1)):
            row = dict(value)
            row[field] = bad
            self.refused(encode([row]))

    def test_GN09_known_stats_types_and_uint64(self):
        for bad in (True, -1, 18446744073709551616, 1.0, "0", None):
            value = interface()
            value["statistics"] = statistics()
            value["statistics"]["rx-bytes"] = bad
            self.refused(encode([value]))
        value["statistics"] = {}
        self.refused(encode([value]))

    def test_GN10_prefix_lexemes_before_conversion(self):
        for raw in (b'true', b'24.0', b'2.4e1', b'-0', b'024', b'33', b'"24"'):
            body = b'{"data":{"result":[{"name":"eth0","ip-addresses":[{"ip-address":"192.0.2.1","ip-address-type":"ipv4","prefix":' + raw + b'}]}]}}'
            self.refused(body)

    def test_GN11_family_literal_and_prefix(self):
        for family, address, prefix in (("ipv4", "::1", 32), ("ipv6", "127.0.0.1", 128),
                                        ("ipv6", "fe80::1%eth0", 64), ("ipv6", "::1", 129),
                                        ("ipv4", "192.0.2.1/24", 24), ("ipv4", "http://host", 0)):
            value = interface()
            value["ip-addresses"] = [{"ip-address": address, "ip-address-type": family, "prefix": prefix}]
            self.refused(encode([value]))

    def test_GN12_reported_loopback_and_zero_prefix(self):
        value = interface()
        value["ip-addresses"] = [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4", "prefix": 0},
                                 {"ip-address": "::1", "ip-address-type": "ipv6", "prefix": 128}]
        self.assertEqual([a["address"] for a in decode_guest_network(encode([value]))[0]["addresses"]],
                         ["127.0.0.1", "::1"])

    def test_GN13_unknown_scalars_charged_then_discarded(self):
        value = {"name": "lo", "unused": "x" * 4096, "flag": True, "absent": None}
        self.assertEqual(decode_guest_network(encode([value])), [{"name": "lo", "mac": None, "addresses": []}])
        value["unused"] += "x"
        self.refused(encode([value]))
        for bad in ({}, []):
            value["unused"] = bad
            self.refused(encode([value]))

    def test_GN14_numeric_lexeme_64_and_nonfinite_tokens(self):
        prefix = b'{"data":{"result":[{"name":"lo","unused":'
        suffix = b'}]}}'
        self.assertEqual(decode_guest_network(prefix + b'1' * 64 + suffix)[0]["name"], "lo")
        for bad in (b'1' * 65, b'NaN', b'Infinity', b'-Infinity', b'1.', b'+1', b'1e'):
            self.refused(prefix + bad + suffix)

    def test_GN15_raw_body_cap_and_trailing_data(self):
        body = encode([])
        self.assertEqual(decode_guest_network(body + b' ' * (262144 - len(body))), [])
        self.refused(body + b' ' * (262145 - len(body)))
        for suffix in (b'{}', b' true', b'\x00'):
            self.refused(body + suffix)

    def test_GN16_generic_depth_and_scalar_budget(self):
        self.assertEqual(Reader(b'[' * 6 + b'0' + b']' * 6).read(), [[[[[["0"]]]]]])
        for body in (b'[' * 7 + b'0' + b']' * 7, b'[' + b','.join([b'0'] * 4097) + b']'):
            with self.assertRaises(Refused):
                Reader(body).read()
        self.assertEqual(len(Reader(b'[' + b','.join([b'0'] * 4096) + b']').read()), 4096)

    def test_GN17_generic_member_and_key_budget(self):
        value = {"x" + str(i): 0 for i in range(128)}
        self.assertEqual(len(Reader(json.dumps(value).encode()).read()), 128)
        value["extra"] = 0
        with self.assertRaises(Refused):
            Reader(json.dumps(value).encode()).read()
        self.assertEqual(len(next(iter(Reader(b'{"' + b'x' * 64 + b'":0}').read()))), 64)
        with self.assertRaises(Refused):
            Reader(b'{"' + b'x' * 65 + b'":0}').read()

    def test_GN18_generic_aggregate_string_budget(self):
        body = json.dumps(["x" * 4096] * 16).encode()
        self.assertEqual(sum(len(s) for s in Reader(body).read()), 65536)
        with self.assertRaises(Refused):
            Reader(json.dumps(["x" * 4096] * 16 + ["x"]).encode()).read()

    def test_GN19_malformed_json_and_types(self):
        for body in (b'', b'{', b'{"data":{"result":[],}}', b'{"data":{"result":[,]}}',
                     b'{"data":{"result":[{"name":"lo","ip-addresses":null}]}}',
                     b'{"data":{"result":[{"name":"lo","statistics":[]}]}}',
                     encode([None]), b'{"data":{"result":[{"name":"lo"}]}}junk'):
            self.refused(body)
        self.refused(bytearray(encode([])))

    def test_GN20_duplicate_mac_and_order_do_not_join(self):
        values = [interface(), interface()]
        values[1]["name"] = "eth1"
        output = decode_guest_network(encode(values))
        self.assertEqual([row["name"] for row in output], ["eth0", "eth1"])
        self.assertEqual(output[0]["mac"], output[1]["mac"])
        self.assertEqual(set(output[0]), {"name", "mac", "addresses"})


    def test_GN21_global_members_independent_of_other_caps(self):
        # Empty array values consume no scalar budget. Every object remains at
        # 128 members; every array remains far below its own 4096-item cap.
        objects = [{"k" + str(i): [] for i in range(128)} for _ in range(32)]
        accepted = Reader(json.dumps(objects, separators=(",", ":")).encode()).read()
        self.assertEqual(sum(len(row) for row in accepted), 4096)
        self.assertEqual(len(accepted), 32)
        objects.append({"extra": []})
        with self.assertRaises(Refused):
            Reader(json.dumps(objects, separators=(",", ":")).encode()).read()

    def test_GN22_global_scalars_independent_of_array_cap(self):
        # Both arrays are shorter than 4096 in both cases. Object members and
        # decoded-string budgets are unused, isolating the global scalar cap.
        arrays = [[0] * 2048, [0] * 2048]
        accepted = Reader(json.dumps(arrays, separators=(",", ":")).encode()).read()
        self.assertEqual([len(row) for row in accepted], [2048, 2048])
        self.assertEqual(sum(map(len, accepted)), 4096)
        arrays[1].append(0)
        with self.assertRaises(Refused):
            Reader(json.dumps(arrays, separators=(",", ":")).encode()).read()


    def test_GN23_ascii_keys_before_unknown_discard(self):
        # Decoded keys must be ASCII, including unknown fields. Escapes cannot
        # disguise non-ASCII keys; literal display values remain Unicode.
        for body in (b'{"\xc3\xa9":0}', b'{"\\u00e9":0}',
                     b'{"\\ud83d\\ude00":null}'):
            with self.assertRaises(Refused):
                Reader(body).read()
        self.assertEqual(Reader(b'{"\\u0061":0}').read(), {"a": "0"})
        self.assertEqual(next(iter(Reader(b'{"' + b'x' * 64 + b'":0}').read())), "x" * 64)
        for key in ("é", "😀"):
            row = {"name": "é", key: 1}
            self.refused(encode([row]))
            row = interface()
            row["statistics"] = statistics()
            row["statistics"][key] = None
            self.refused(encode([row]))
        self.assertEqual(decode_guest_network(encode([{"name": "é", "ascii": 1}]))[0]["name"], "é")


if __name__ == "__main__":
    unittest.main()
