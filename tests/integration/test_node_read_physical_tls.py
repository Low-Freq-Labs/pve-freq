"""Prepared physical TLS cases; requires approved synthetic assets explicitly.

Run only after runtime/packet qualification. No socket, TLS pump or exchange is
mocked. The only destination is127.0.0.1:8006; fixture bind conflicts fail closed.
"""
import os
from pathlib import Path
import ssl
import unittest

from freq.services.node_read_exchange import OriginalExchange
from freq.services.node_read_profile import WireTarget
from node_read_tls_peer import LoopbackPeer


CREDENTIALS = ("fictional@realm", "fixture", "not-a-real-secret")
VALID = (b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n"
         b"Content-Type: application/json\r\nConnection: close\r\n\r\n"
         b'{"data":[]}')


class PhysicalTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Packet launcher must pin these public synthetic fixture inputs. No
        # product vault, default credential resolver or production trust runs.
        root = Path(os.environ["NODE_SYNTHETIC_TLS_ROOT"])
        cls.name = os.environ["NODE_SYNTHETIC_TLS_DNS_NAME"]
        WireTarget("127.0.0.1", cls.name, "node")
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(root / "server.crt", root / "server.key")
        cls.client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        cls.client_context.load_verify_locations(cafile=str(root / "server.crt"))

    def exchange(self, context, name, response, *, handshake_rejection=False):
        peer = LoopbackPeer(self.server_context, response)
        owner = OriginalExchange()
        result = None
        fault = None
        try:
            peer.start()
            result = owner.run(WireTarget("127.0.0.1", name, "node"),
                               CREDENTIALS, context)
        except BaseException as error:
            fault = error
        finally:
            # Both cleanup boundaries are observed; neither is inferred from
            # a client result. Peer.finish propagates original thread faults.
            for cleanup in (owner._socket_owner.close, peer.finish):
                try:
                    cleanup()
                except BaseException as error:
                    if fault is None or (isinstance(fault, Exception)
                                         and not isinstance(error, Exception)):
                        fault = error
        if fault is not None:
            raise fault
        self.assertEqual(peer.accepted, 1)
        self.assertTrue(owner._socket_owner._spent)
        self.assertIsNone(owner._socket_owner._socket)
        self.assertTrue(peer.listener_closed)
        self.assertTrue(peer.connection_closed)
        self.assertFalse(peer.thread.is_alive())
        if handshake_rejection:
            self.assertTrue(peer.handshake_rejected)
            self.assertFalse(peer.request_complete)
            self.assertEqual(peer.request_bytes, 0)
        else:
            self.assertTrue(peer.handshake_completed)
            self.assertTrue(peer.request_complete)
            self.assertLessEqual(peer.request_bytes, 4096)
        return result

    def test_verified_chain_and_dns_name_returns_exact_body(self):
        self.assertEqual(self.exchange(self.client_context, self.name, VALID),
                         b'{"data":[]}')

    def test_wrong_dns_name_refuses_before_http_request(self):
        wrong = "wrong-name.invalid" if self.name != "wrong-name.invalid" else "other.invalid"
        self.assertIsNone(self.exchange(self.client_context, wrong, VALID,
                                       handshake_rejection=True))

    def test_empty_trust_store_refuses_before_http_request(self):
        empty_trust = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertIsNone(self.exchange(empty_trust, self.name, VALID,
                                       handshake_rejection=True))

    def test_duplicate_length_refused_over_actual_tls(self):
        wire = VALID.replace(b"Content-Length: 11\r\n",
                             b"Content-Length: 11\r\nContent-Length: 11\r\n")
        self.assertIsNone(self.exchange(self.client_context, self.name, wire))

    def test_short_body_refused_over_actual_tls(self):
        wire = VALID[:-1]
        self.assertIsNone(self.exchange(self.client_context, self.name, wire))
