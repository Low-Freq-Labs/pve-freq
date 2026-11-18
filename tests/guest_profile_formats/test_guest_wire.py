"""Original finite fixtures; unrun source, for qualified offline execution only."""

import copy
import json
import unittest

from freq.services.guest_profile_formats.guest_wire import Refused, project_guest_wire


T = "2026-10-24T04:00:00.000Z"


def section(outcome="reported", data=None):
    return {"outcome": outcome, "observed_at": T if outcome == "reported" else None,
            "data": data}


def profile():
    return {"schema": 1, "kind": "guest-profile",
            "target": {"source_label": "Branch", "node": "branch-pve", "guest_kind": "qemu",
                       "vmid": 120, "name": "test"}, "completed_at": T,
            "status": section(data={"state": "running", "cpu_fraction": 0.5,
                                    "memory_used_bytes": 0, "memory_limit_bytes": 9007199254740991}),
            "configured_network": section(data=[]), "guest_network": section(data=[])}


def inventory(count=256, name=None):
    return {"schema": 1, "kind": "guest-inventory", "source_label": "Branch",
            "observed_at": T, "completed_at": T,
            "guests": [{"guest_ref": format(i, "064x"), "node": "branch-pve",
                        "guest_kind": "qemu", "vmid": 100 + i, "name": name}
                       for i in range(count)]}


class WireTests(unittest.TestCase):
    def refused(self, value):
        with self.assertRaises(Refused) as ctx:
            project_guest_wire(value)
        self.assertEqual(str(ctx.exception), "Guest wire unavailable")

    def test_GW01_reported_empty_and_partial(self):
        value = profile()
        value["guest_network"] = section("unavailable")
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        self.assertEqual(value["configured_network"]["data"], [])

    def test_GW02_lxc_only_unsupported(self):
        value = profile()
        value["target"]["guest_kind"] = "lxc"
        for key in ("status", "configured_network", "guest_network"):
            value[key] = section("unsupported")
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        value["status"] = section("unavailable")
        self.refused(value)

    def test_GW03_unavailable_cannot_contain_data_or_time(self):
        for field, bad in (("data", []), ("observed_at", T)):
            value = profile()
            value["guest_network"] = section("unavailable")
            value["guest_network"][field] = bad
            self.refused(value)

    def test_GW04_unknown_keys_and_bad_schema(self):
        for mutate in (lambda v: v.update(extra="secret"), lambda v: v.update(schema=True),
                       lambda v: v["target"].update(url="https://untrusted.invalid")):
            value = profile()
            mutate(value)
            self.refused(value)

    def test_GW05_exact_builtin_types_no_hooks(self):
        class Hostile(dict):
            def get(self, *args):
                raise AssertionError("Object hook called")
        self.refused(Hostile(profile()))
        value = profile()
        value["target"]["vmid"] = True
        self.refused(value)
        value = profile()
        value["guest_network"]["data"] = ()
        self.refused(value)

    def test_GW06_inventory_rows_and_unique_tuple(self):
        value = inventory()
        self.assertEqual(len(json.loads(project_guest_wire(value))["guests"]), 256)
        self.refused(inventory(257))
        value["guests"][-1]["vmid"] = value["guests"][0]["vmid"]
        self.refused(value)

    def test_GW07_inventory_duplicate_and_malformed_refs(self):
        value = inventory(2)
        value["guests"][1]["guest_ref"] = value["guests"][0]["guest_ref"]
        self.refused(value)
        for ref in ("a" * 63, "A" * 64, "g" * 64, 1):
            value = inventory(1)
            value["guests"][0]["guest_ref"] = ref
            self.refused(value)

    def test_GW08_sources_bound_and_unique(self):
        value = {"schema": 1, "kind": "guest-sources", "completed_at": T,
                 "sources": [{"source_ref": format(i, "064x"), "label": "Source"} for i in range(32)]}
        self.assertEqual(len(json.loads(project_guest_wire(value))["sources"]), 32)
        value["sources"].append({"source_ref": "f" * 64, "label": "Other"})
        self.refused(value)
        value["sources"].pop()
        value["sources"][1]["source_ref"] = value["sources"][0]["source_ref"]
        self.refused(value)

    def test_GW09_utf8_string_bound_and_surrogates(self):
        value = profile()
        value["target"]["name"] = "é" * 128
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        value["target"]["name"] += "é"
        self.refused(value)
        value["target"]["name"] = "\ud800"
        self.refused(value)

    def test_GW10_calendar_and_timestamp_shape(self):
        for timestamp in ("2026-02-30T00:00:00.000Z", "2026-10-24T04:00:00Z",
                          "2026-10-24T04:00:60.000Z", "2026-10-24T04:00:00.000+00:00"):
            value = profile()
            value["completed_at"] = timestamp
            self.refused(value)

    def test_GW11_numeric_optional_and_edges(self):
        value = profile()
        for cpu in (None, 0, 1, 0.0, 1.0):
            value["status"]["data"]["cpu_fraction"] = cpu
            self.assertEqual(json.loads(project_guest_wire(value)), value)
        for field, bad in (("cpu_fraction", True), ("cpu_fraction", float("nan")),
                           ("cpu_fraction", float("inf")), ("cpu_fraction", -0.01),
                           ("cpu_fraction", 1.01), ("memory_used_bytes", True),
                           ("memory_limit_bytes", 9007199254740992)):
            value = profile()
            value["status"]["data"][field] = bad
            self.refused(value)

    def test_GW12_reported_addresses_preserved(self):
        value = profile()
        addresses = [{"family": "ipv4", "address": "127.0.0.1", "prefix": 32},
                     {"family": "ipv6", "address": "fe80::1", "prefix": 64},
                     {"family": "ipv6", "address": "::1", "prefix": 128}]
        value["guest_network"]["data"] = [{"name": "lo", "mac": None, "addresses": addresses}]
        self.assertEqual(json.loads(project_guest_wire(value)), value)

    def test_GW13_invalid_address_prefix_family(self):
        for address in ({"family": "ipv4", "address": "::1", "prefix": 32},
                        {"family": "ipv6", "address": "fe80::1%eth0", "prefix": 64},
                        {"family": "ipv4", "address": "127.0.0.1", "prefix": True},
                        {"family": "ipv6", "address": "::1", "prefix": 129},
                        {"family": "ipv4", "address": "http://127.0.0.1", "prefix": 0}):
            value = profile()
            value["guest_network"]["data"] = [{"name": "eth0", "mac": None, "addresses": [address]}]
            self.refused(value)

    def test_GW14_network_collection_edges(self):
        value = profile()
        address = {"family": "ipv4", "address": "1.2.3.4", "prefix": 24}
        value["guest_network"]["data"] = [{"name": "eth0", "mac": "not-a-match", "addresses": []} for _ in range(64)]
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        value["guest_network"]["data"].append({"name": "eth1", "mac": None, "addresses": []})
        self.refused(value)
        value["guest_network"]["data"] = [{"name": "eth0", "mac": None, "addresses": [address] * 16}]
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        value["guest_network"]["data"][0]["addresses"].append(address)
        self.refused(value)

    def test_GW15_configured_nic_key_vlan_and_duplicates(self):
        value = profile()
        row = {"key": "net31", "model": None, "mac": "invalid", "bridge": None,
               "vlan": 4094, "addresses": [], "gateways": []}
        value["configured_network"]["data"] = [row]
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        for field, bad in (("key", "net32"), ("key", "net01"), ("vlan", 4095), ("vlan", False)):
            bad_value = copy.deepcopy(value)
            bad_value["configured_network"]["data"][0][field] = bad
            self.refused(bad_value)
        value["configured_network"]["data"].append(copy.deepcopy(row))
        self.refused(value)

    def test_GW16_snapshot_and_literal_content(self):
        value = profile()
        value["target"]["name"] = '<img src=x onerror="bad()">'
        original = copy.deepcopy(value)
        encoded = project_guest_wire(value)
        value["target"]["name"] = "changed later"
        self.assertEqual(json.loads(encoded), original)

    def test_GW17_string_budget_counts_keys(self):
        value = inventory()
        def string_bytes(node):
            if type(node) is str:
                return len(node.encode("utf-8"))
            if type(node) is dict:
                return sum(len(k.encode("utf-8")) + string_bytes(v) for k, v in node.items())
            if type(node) is list:
                return sum(map(string_bytes, node))
            return 0
        remaining = 65536 - string_bytes(value)
        for row in value["guests"]:
            size = min(remaining, 256)
            row["name"] = "x" * size
            remaining -= size
        self.assertEqual(remaining, 0)
        self.assertEqual(string_bytes(value), 65536)
        self.assertEqual(json.loads(project_guest_wire(value)), value)
        next(row for row in value["guests"] if len(row["name"]) < 256)["name"] += "x"
        self.assertEqual(string_bytes(value), 65537)
        self.refused(value)

    def test_GW18_serialized_bytes_limit_separate_from_strings(self):
        value = inventory(name="\x00" * 120)
        # Controls are valid literal text but require JSON escaping. The full
        # response byte bound must refuse despite bounded field/decoded sizes.
        self.assertGreater(len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()), 131072)
        self.refused(value)

    def test_GW19_unknown_outcomes_and_absent_reported_data(self):
        for outcome, data in (("success", []), ("reported", None)):
            value = profile()
            value["guest_network"] = section(outcome, data)
            self.refused(value)

    def test_GW20_fixed_unavailable(self):
        self.assertEqual(project_guest_wire({"schema": 1, "kind": "guest-unavailable"}),
                         b'{"kind":"guest-unavailable","schema":1}')


if __name__ == "__main__":
    unittest.main()
