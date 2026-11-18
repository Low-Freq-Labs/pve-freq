"""Fictional configured-network cases. All candidate execution remains gated."""

import json
import unittest

from freq.services.guest_profile_formats.guest_config import Refused, decode_guest_config, properties


MAC = "02:00:00:00:00:01"


def body(value):
    return json.dumps({"data": value}, ensure_ascii=False,
                      separators=(",", ":")).encode()


class ConfigTests(unittest.TestCase):
    def refused(self, raw):
        with self.assertRaises(Refused) as caught:
            decode_guest_config(raw)
        self.assertEqual(str(caught.exception), "Guest configuration unavailable")

    def test_GC01_literal_nic_and_same_index_static_configuration(self):
        value = {"net0": "virtio=" + MAC + ",bridge=br-test,tag=7",
                 "ipconfig0": "ip=192.0.2.10/24,gw=192.0.2.1"}
        self.assertEqual(decode_guest_config(body(value)),
                         [{"key": "net0", "model": "virtio", "mac": MAC,
                           "bridge": "br-test", "vlan": 7,
                           "addresses": [{"family": "ipv4", "address": "192.0.2.10", "prefix": 24}],
                           "gateways": [{"family": "ipv4", "address": "192.0.2.1"}]}])

    def test_GC02_nic_and_address_source_order(self):
        value = {"ipconfig2": "ip6=FE80::1/64,ip=192.0.2.2/24", "net2": "virtio",
                 "net0": "e1000", "ipconfig0": "ip=198.51.100.2/24"}
        result = decode_guest_config(body(value))
        self.assertEqual([row["key"] for row in result], ["net2", "net0"])
        self.assertEqual([a["address"] for a in result[0]["addresses"]], ["FE80::1", "192.0.2.2"])
        self.assertEqual(result[1]["addresses"][0]["address"], "198.51.100.2")

    def test_GC03_empty_optional_no_generated_mac_or_address(self):
        self.assertEqual(decode_guest_config(body({})), [])
        result = decode_guest_config(body({"net0": "virtio", "ipconfig0": ""}))[0]
        self.assertEqual((result["mac"], result["bridge"], result["vlan"]), (None, None, None))
        self.assertEqual((result["addresses"], result["gateways"]), ([], []))

    def test_GC04_explicit_and_alias_models(self):
        for value in ("virtio=" + MAC, "model=virtio,macaddr=" + MAC):
            row = decode_guest_config(body({"net0": value}))[0]
            self.assertEqual((row["model"], row["mac"]), ("virtio", MAC))
        for value in ("macaddr=" + MAC, "model=unknown", "unknown=" + MAC):
            self.refused(body({"net0": value}))

    def test_GC05_duplicate_properties_and_alias_collisions(self):
        for value in ("virtio=" + MAC + ",virtio=" + MAC,
                      "virtio=" + MAC + ",model=virtio",
                      "model=virtio,virtio=" + MAC,
                      "macaddr=" + MAC + ",virtio=" + MAC,
                      "virtio=" + MAC + ",macaddr=" + MAC,
                      "virtio,bridge=a,bridge=b", "virtio,firewall=1,firewall=0"):
            self.refused(body({"net0": value}))
        self.refused(body({"net0": "virtio", "ipconfig0": "ip=dhcp,ip=192.0.2.1/24"}))

    def test_GC06_ambiguous_escapes_empty_tokens_and_whitespace(self):
        for value in ("", "virtio,", ",virtio", "virtio,,tag=7", "virtio=", "virtio,tag==7",
                      "virtio,bridge='br0'", 'virtio,bridge="br0"', "virtio,bridge=br\\,0",
                      "virtio, bridge=br0", "virtio\n", "virtio,bridge=é"):
            self.refused(body({"net0": value}))

    def test_GC07_known_ignored_options_do_not_become_controls(self):
        value = "virtio,firewall=1,link_down=0,host-tunnel=1,queues=64,mtu=65520,rate=0.25,trunks=1;2-7"
        row = decode_guest_config(body({"net0": value}))[0]
        self.assertEqual(set(row), {"key", "model", "mac", "bridge", "vlan", "addresses", "gateways"})
        for option in ("firewall=true", "link_down=2", "queues=65", "queues=01", "mtu=0",
                       "mtu=65521", "rate=1e2", "rate=-1", "other=1"):
            self.refused(body({"net0": "virtio," + option}))

    def test_GC08_nic_indices_and_types(self):
        value = {"net" + str(i): "virtio" for i in range(32)}
        self.assertEqual(len(decode_guest_config(body(value))), 32)
        value["net32"] = "virtio"
        self.refused(body(value))
        for key in ("net00", "ipconfig00", "ipconfig32"):
            self.refused(body({"net0": "virtio", key: "" if key.startswith("ip") else "virtio"}))
        for value in (None, True, 1, [], {}):
            self.refused(body({"net0": value}))

    def test_GC09_mac_literal_validity_and_duplicates(self):
        mac = "AA:BB:CC:DD:EE:FF"
        rows = decode_guest_config(body({"net0": "virtio=" + mac, "net1": "e1000=" + mac}))
        self.assertEqual([row["mac"] for row in rows], [mac, mac])
        for mac in ("bad", "00-11-22-33-44-55", "00:11:22:33:44", "GG:11:22:33:44:55"):
            self.refused(body({"net0": "virtio=" + mac}))

    def test_GC10_bridge_literal_bound(self):
        bridge = "b" * 128
        self.assertEqual(decode_guest_config(body({"net0": "virtio,bridge=" + bridge}))[0]["bridge"], bridge)
        for bridge in ("b" * 129, "-bad", "http://host", "has space"):
            self.refused(body({"net0": "virtio,bridge=" + bridge}))

    def test_GC11_provider_vlan_subset(self):
        for vlan in (1, 4094):
            self.assertEqual(decode_guest_config(body({"net0": "virtio,tag=" + str(vlan)}))[0]["vlan"], vlan)
        for value in ("0", "4095", "-1", "+1", "01", "1.0", "1e0"):
            self.refused(body({"net0": "virtio,tag=" + value}))

    def test_GC12_ipv4_literal_and_prefix_bounds(self):
        for value, prefix in (("0.0.0.0/0", 0), ("127.0.0.1/32", 32)):
            row = decode_guest_config(body({"net0": "virtio", "ipconfig0": "ip=" + value}))[0]
            self.assertEqual(row["addresses"][0]["prefix"], prefix)
        for value in ("192.0.2.1/33", "192.0.2.1/024", "192.0.2.1/-1", "192.0.2.1",
                      "192.000.2.1/24", "192.0.2.1:80/24", "http://host/24", "::1/24"):
            self.refused(body({"net0": "virtio", "ipconfig0": "ip=" + value}))

    def test_GC13_ipv6_literal_spelling_and_family(self):
        for value in ("::1/128", "FE80::A/64", "::ffff:192.0.2.1/96"):
            row = decode_guest_config(body({"net0": "virtio", "ipconfig0": "ip6=" + value}))[0]
            self.assertEqual(row["addresses"][0]["address"], value.split("/")[0])
        for value in ("::1/129", "fe80::1%eth0/64", "[::1]/64", "127.0.0.1/64", "::1//64"):
            self.refused(body({"net0": "virtio", "ipconfig0": "ip6=" + value}))

    def test_GC14_dhcp_auto_and_gateway_require_static_family(self):
        for value in ("ip=dhcp", "ip6=auto", "ip6=dhcp", "ip=dhcp,ip6=auto"):
            row = decode_guest_config(body({"net0": "virtio", "ipconfig0": value}))[0]
            self.assertEqual((row["addresses"], row["gateways"]), ([], []))
        for value in ("gw=192.0.2.1", "ip=dhcp,gw=192.0.2.1", "ip6=auto,gw6=fe80::1",
                      "ip6=dhcp,gw6=fe80::1", "ip=auto", "ip=192.0.2.1/24,gw=::1"):
            self.refused(body({"net0": "virtio", "ipconfig0": value}))

    def test_GC15_no_orphan_or_cross_index_association(self):
        self.refused(body({"net0": "virtio", "ipconfig1": "ip=192.0.2.1/24"}))
        self.refused(body({"ipconfig0": "ip=dhcp"}))
        row = decode_guest_config(body({"net0": "virtio", "net1": "virtio", "ipconfig1": "ip=192.0.2.1/24"}))
        self.assertEqual(row[0]["addresses"], [])
        self.assertEqual(row[1]["addresses"][0]["address"], "192.0.2.1")

    def test_GC16_unknown_scalar_fields_discarded(self):
        value = {"net0": "virtio", "description": "<b>fictional</b>", "sshkeys": "fictional",
                 "disk0": "fictional", "cores": 2, "unused": None}
        self.assertEqual(len(decode_guest_config(body(value))), 1)
        for extra in ([], {}):
            self.refused(body({"net0": "virtio", "unknown": extra}))

    def test_GC17_exact_json_wrapper(self):
        for raw in (b'[]', b'{}', b'{"data":[]}', b'{"data":null}', b'{"data":{},"extra":0}'):
            self.refused(raw)

    def test_GC18_decoded_duplicate_and_ascii_keys(self):
        for raw in (b'{"data":{"net0":"virtio","net0":"e1000"}}',
                    b'{"data":{"net0":"virtio","net\\u0030":"e1000"}}',
                    b'{"data":{"\\u00e9":0}}'):
            self.refused(raw)

    def test_GC19_utf8_bom_surrogates_and_unknown_unicode_value(self):
        for raw in (b'\xff', b'\xef\xbb\xbf' + body({}), b'{"data":{"unknown":"\\ud800"}}'):
            self.refused(raw)
        self.assertEqual(decode_guest_config(body({"unknown": "é😀"})), [])

    def test_GC20_raw_byte_cap_eof_and_exact_bytes(self):
        raw = body({})
        self.assertEqual(decode_guest_config(raw + b' ' * (262144 - len(raw))), [])
        for bad in (raw + b' ' * (262145 - len(raw)), raw + b'{}', raw + b'\x00', bytearray(raw), raw.decode()):
            self.refused(bad)

    def test_GC21_global_string_budget_including_keys(self):
        value = {"k" + str(i): "x" * 4096 for i in range(15)}
        overhead = len("data") + sum(map(len, value)) + len("tail")
        value["tail"] = "y" * (65536 - 15 * 4096 - overhead)
        self.assertEqual(decode_guest_config(body(value)), [])
        value["tail"] += "y"
        self.refused(body(value))

    def test_GC22_property_scanner_only_caps(self):
        # These are parser-helper maxima, not valid selected NIC/IP schemas.
        value = ",".join("k" + str(i) + "=x" for i in range(32))
        self.assertEqual(len(properties(value)), 32)
        for bad in (value + ",extra=x", "k=" + "x" * 4095):
            with self.assertRaises(Refused):
                properties(bad)
        self.assertEqual(len(properties("k=" + "x" * 4094)["k"]), 4094)

    def test_GC23_trunks_bounds_and_ranges(self):
        value = "virtio,trunks=" + ";".join(str(i) for i in range(1, 65))
        self.assertEqual(decode_guest_config(body({"net0": value}))[0]["model"], "virtio")
        for suffix in (";65",):
            self.refused(body({"net0": value + suffix}))
        for trunks in ("0", "2-1", "4095", "01", "1-2-3", ";1"):
            self.refused(body({"net0": "virtio,trunks=" + trunks}))

    def test_GC24_late_invalid_whole_refusal_and_independent_results(self):
        self.refused(body({"net0": "virtio", "net1": "bad"}))
        raw = body({"net0": "virtio", "ipconfig0": "ip=192.0.2.1/24"})
        first = decode_guest_config(raw)
        first[0]["addresses"][0]["address"] = "modified"
        second = decode_guest_config(raw)
        self.assertEqual(second[0]["addresses"][0]["address"], "192.0.2.1")


if __name__ == "__main__":
    unittest.main()
