"""Fictional request boundary fixtures; designated runtime only."""
import unittest
from unittest.mock import patch

from freq.services import node_read_profile as profile


class RequestProfileCases(unittest.TestCase):
    def target(self, endpoint="192.0.2.10", node="fixture-node"):
        return profile.WireTarget(endpoint, "node.example.invalid", node)

    def test_ipv4_exact_bytes(self):
        self.assertEqual(
            profile.serialize_request(self.target(), ("fixture@realm", "read", "fictional")),
            b"GET /api2/json/nodes/fixture-node/network HTTP/1.1\r\n"
            b"Host: 192.0.2.10:8006\r\n"
            b"Authorization: PVEAPIToken=fixture@realm!read=fictional\r\n"
            b"Accept: application/json\r\nConnection: close\r\n\r\n",
        )

    def test_ipv6_host_is_distinct_from_tls_name(self):
        result = profile.serialize_request(
            self.target("2001:0db8:0000:0000:0000:0000:0000:0001"),
            ("fixture@realm", "read", "fictional"),
        )
        self.assertIn(b"Host: [2001:db8::1]:8006\r\n", result)
        self.assertNotIn(b"node.example.invalid", result)

    def test_credential_component_maxima(self):
        result = profile.serialize_request(
            self.target(node="n" * 128),
            ("u" * 128 + "@" + "r" * 128, "t" * 128, "s" * 512),
        )
        self.assertLessEqual(len(result), 4096)
        self.assertEqual(result.count(b"\r\n"), 6)

    def test_credential_excess(self):
        for credentials in (
            ("u" * 129 + "@r", "t", "s"),
            ("u@" + "r" * 129, "t", "s"),
            ("u@r", "t" * 129, "s"),
            ("u@r", "t", "s" * 513),
        ):
            with self.subTest(lengths=tuple(map(len, credentials))):
                with self.assertRaises(ValueError):
                    profile.serialize_request(self.target(), credentials)

    def test_credential_control_and_encoding_refusal(self):
        for bad in ("\r", "\n", "\x00", "\x1f", "\x7f", " ", "\t", "é", "\ud800"):
            for index in range(3):
                values = ["fixture@realm", "token", "fictional"]
                values[index] += bad
                with self.assertRaises(ValueError):
                    profile.serialize_request(self.target(), tuple(values))

    def test_exact_types(self):
        class Text(str):
            pass

        class Credentials(tuple):
            pass

        for value in ([], None, True, ("u@r", "t"), Credentials(("u@r", "t", "s"))):
            with self.assertRaises(ValueError):
                profile.serialize_request(self.target(), value)
        for index in range(3):
            values = ["u@r", "t", "s"]
            values[index] = Text(values[index])
            with self.assertRaises(ValueError):
                profile.serialize_request(self.target(), tuple(values))

    def test_endpoint_refusals(self):
        for address in ("localhost", "192.0.2.1:8006", "[2001:db8::1]", "fe80::1%eth0", "127.1", ""):
            with self.assertRaises(ValueError):
                self.target(address)

    def test_dns_name_boundaries(self):
        name = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61))
        self.assertEqual(len(name), 253)
        self.assertEqual(profile.WireTarget("192.0.2.10", name, "n").tls_name, name)
        for invalid in (name + "e", "a" * 64 + ".invalid", "a..invalid", "a.invalid.", "-a.invalid", "a-.invalid", "*.invalid"):
            with self.assertRaises(ValueError):
                profile.WireTarget("192.0.2.10", invalid, "n")

    def test_node_segment_refusals(self):
        for node in ("", "n" * 129, "a/b", "..", "a%2fb", "a?x=1", "a\r\nHost:x"):
            with self.assertRaises(ValueError):
                self.target(node=node)

    def test_aggregate_guard_separately(self):
        # Component bounds make a 4097-byte admitted request unreachable.
        # Exercise the serializer's aggregate guard with a lowered test cap.
        target = self.target()
        credentials = ("u@r", "t", "s")
        request = profile.serialize_request(target, credentials)
        with patch.object(profile, "REQUEST_LIMIT", len(request)):
            self.assertEqual(profile.serialize_request(target, credentials), request)
        with patch.object(profile, "REQUEST_LIMIT", len(request) - 1):
            with self.assertRaises(ValueError):
                profile.serialize_request(target, credentials)


if __name__ == "__main__":
    unittest.main()
