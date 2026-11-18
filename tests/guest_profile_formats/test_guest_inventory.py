import json
import unittest

from freq.services.guest_profile_formats.guest_inventory import Refused, decode_guest_inventory


def wire(rows):
    return json.dumps({"data": rows}, ensure_ascii=False, separators=(",", ":")).encode()


def row(vmid=100, **fields):
    return dict(type="qemu", node="pve-1", vmid=vmid, **fields)


class InventoryTests(unittest.TestCase):
    def bad(self, value):
        with self.assertRaisesRegex(Refused, "^Guest inventory unavailable$"):
            decode_guest_inventory(value)

    def test_GI01_order_and_literal_qemu_lxc(self):
        data = [row(120, name="<literal>"), dict(type="lxc", node="HQ.1", vmid=101, name="ct")]
        self.assertEqual(decode_guest_inventory(wire(data)), [
            dict(node="pve-1", guest_kind="qemu", vmid=120, name="<literal>"),
            dict(node="HQ.1", guest_kind="lxc", vmid=101, name="ct")])

    def test_GI02_empty_observed_is_distinct_from_bad_body(self):
        self.assertEqual(decode_guest_inventory(b'{"data":[]}'), [])
        for body in (b"", b"null", b"{}", b'{"data":null}', b'{"data":[]}:'):
            self.bad(body)

    def test_GI03_no_tuple_cross_source_or_kind_guess(self):
        self.assertEqual(len(decode_guest_inventory(wire([
            row(120), dict(type="lxc", node="pve-1", vmid=120),
            dict(type="qemu", node="PVE-1", vmid=120)]))), 3)

    def test_GI04_duplicate_tuple_refuses_even_changed_name(self):
        self.bad(wire([row(name="a"), row(name="b")]))

    def test_GI05_complete_application_row_boundary(self):
        data = [row(100+i) for i in range(256)]
        self.assertEqual(len(decode_guest_inventory(wire(data))), 256)
        self.bad(wire(data+[row(356)]))

    def test_GI06_raw_rows_charged_before_non_guest_discard(self):
        data = [dict(type="node", ignored=1) for _ in range(4096)]
        self.assertEqual(decode_guest_inventory(wire(data)), [])
        self.bad(wire(data+[dict(type="node")]))

    def test_GI07_missing_and_malformed_type_refuse(self):
        for kind in (None, True, 1, [], {}):
            self.bad(wire([dict(type=kind, node="pve-1", vmid=100)]))
        self.bad(wire([dict(node="pve-1", vmid=100)]))
        self.bad(wire([dict(type="", node="pve-1", vmid=100)]))
        self.assertEqual(decode_guest_inventory(wire([dict(type="QEMU") ])), [])

    def test_GI08_node_ascii_and_positive_neighbor(self):
        self.assertEqual(decode_guest_inventory(wire([dict(type="qemu", node="A"*64, vmid=100)]))[0]["node"], "A"*64)
        for node in (None, 1, True, "", "A"*65, "a_b", " a", "a/", ".a", "é", "a\x00"):
            self.bad(wire([dict(type="qemu", node=node, vmid=100)]))

    def test_GI09_vmid_exact_lexical_integer(self):
        for vmid in (100, 999999999):
            self.assertEqual(decode_guest_inventory(wire([row(vmid)]))[0]["vmid"], vmid)
        for token in (b"99", b"1000000000", b"100.0", b"1e2", b"-100", b"true", b"null", b'"100"', b"0100"):
            self.bad(b'{"data":[{"type":"qemu","node":"pve","vmid":'+token+b'}]}')

    def test_GI10_names_missing_null_empty_and_byte_cap(self):
        for name in (None, "", "a"*256, "é"*128, "\n<literal>"):
            self.assertEqual(decode_guest_inventory(wire([row(name=name)]))[0]["name"], name)
        self.assertIsNone(decode_guest_inventory(wire([row()]))[0]["name"])
        for name in ("a"*257, "é"*129, True, 12, [], {}):
            self.bad(wire([row(name=name)]))

    def test_GI11_templates_not_heuristically_filtered(self):
        self.assertEqual(len(decode_guest_inventory(wire([row(100, template=1), row(101, template=0)]))), 2)

    def test_GI12_unrelated_scalar_fields_not_forwarded(self):
        result = decode_guest_inventory(wire([row(cpu=0.5, mem=5, secret="discard", status="running", tags="x")]))
        self.assertEqual(result, [dict(node="pve-1", guest_kind="qemu", vmid=100, name=None)])

    def test_GI13_unknown_nested_or_invalid_non_guest_refuses_whole(self):
        for tail in (dict(type="node", hidden={}), dict(type="node", hidden=[])):
            self.bad(wire([row(), tail]))
        self.bad(b'{"data":[{"type":"qemu","node":"pve","vmid":100},{"type":"node","x":NaN}]}')

    def test_GI14_decoded_duplicate_keys_refuse(self):
        self.bad(b'{"data":[{"type":"qemu","node":"pve","vmid":100,"na\\u006de":"x","name":"y"}]}')
        self.bad(b'{"data":[],"data":[]}')

    def test_GI15_utf8_bom_surrogates_and_exact_bytes(self):
        for body in (b'\xef\xbb\xbf{"data":[]}', b'{"data":[{"type":"node","x":"\xff"}]}', b'{"data":[{"type":"node","x":"\\ud800"}]}', bytearray(b'{"data":[]}'), '{"data":[]}'):
            self.bad(body)

    def test_GI16_raw_byte_boundary_and_eof(self):
        body = b'{"data":[]}'
        self.assertEqual(decode_guest_inventory(body+b" "*(1048576-len(body))), [])
        self.bad(body+b" "*(1048577-len(body)))
        self.bad(body+b"null")

    def test_GI17_late_invalid_guest_suppresses_provisional_rows(self):
        self.bad(wire([row(100), dict(type="lxc", node="pve-1", vmid=99)]))

    def test_GI18_results_fresh_and_no_authority_fields(self):
        body=wire([row(name="guest")]);one=decode_guest_inventory(body);two=decode_guest_inventory(body)
        self.assertIsNot(one,two);self.assertIsNot(one[0],two[0]);one[0]["name"]="changed"
        self.assertEqual(two[0]["name"],"guest")
        self.assertEqual(set(two[0]),{"node","guest_kind","vmid","name"})
