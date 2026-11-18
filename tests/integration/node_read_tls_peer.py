"""Prepared loopback-only peer for qualified node transport fixtures.

No automatic execution or certificate generation. The selected packet must
supply reviewed synthetic certificate assets and a matching DNS verification
name. A bind conflict fails; this fixture never stops another listener.
"""
import socket
import ssl
import threading
import time


class LoopbackPeer:
    """One accepted connection, bounded request, no retained credential bytes."""

    def __init__(self, server_context, response, *, hold_seconds=0.0):
        if type(server_context) is not ssl.SSLContext:
            raise ValueError("fixture context required")
        if type(response) is not bytes or len(response) > 1100000:
            raise ValueError("fixture response bound")
        if type(hold_seconds) is not float or not 0.0 <= hold_seconds <= 1.0:
            raise ValueError("fixture hold bound")
        self.context = server_context
        self.response = response
        self.hold_seconds = hold_seconds
        self.listener = None
        self.thread = None
        self.accepted = 0
        self.handshake_completed = False
        self.handshake_rejected = False
        self.request_complete = False
        self.request_bytes = 0
        self.connection_closed = False
        self.listener_closed = False
        self.failure = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener = listener
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.settimeout(3.0)
            listener.bind(("127.0.0.1", 8006))
            listener.listen(1)
            self.thread = threading.Thread(target=self._serve, args=(listener,),
                                           name="node-offline-tls-peer")
            self.thread.start()
        except BaseException:
            self.listener = None
            listener.close()
            self.listener_closed = True
            raise

    def _serve(self, original_listener):
        raw = wrapped = None
        try:
            raw, address = original_listener.accept()
            self.accepted += 1
            if address[0] != "127.0.0.1":
                raise ValueError("fixture peer address")
            raw.settimeout(3.0)
            # Standard-library ownership transfer; disable eager handshake so
            # the new original descriptor owner is recorded before handshake.
            wrapped = self.context.wrap_socket(
                raw, server_side=True, do_handshake_on_connect=False)
            raw = None
            try:
                wrapped.do_handshake()
            except ssl.SSLError:
                self.handshake_rejected = True
                return
            self.handshake_completed = True
            request = bytearray()
            while not request.endswith(b"\r\n\r\n"):
                if len(request) >= 4096:
                    raise ValueError("fixture request bound")
                chunk = wrapped.recv(min(512, 4096 - len(request)))
                if not chunk:
                    raise ValueError("fixture incomplete request")
                request.extend(chunk)
            self.request_bytes = len(request)
            # Request payload is fictional and never retained in the receipt.
            self.request_complete = request.startswith(
                b"GET /api2/json/nodes/node/network HTTP/1.1\r\n")
            if not self.request_complete:
                raise ValueError("fixture unexpected request")
            request = None
            chunk = None
            if self.hold_seconds:
                time.sleep(self.hold_seconds)
            for offset in range(0, len(self.response), 16384):
                wrapped.sendall(self.response[offset:offset + 16384])
        except BaseException as error:
            self.failure = error
        finally:
            # A wrapping failure may leave a detached raw object: closing it
            # is safe under the standard socket contract, with no retry.
            original = wrapped if wrapped is not None else raw
            wrapped = raw = None
            if original is not None:
                try:
                    original.close()
                    self.connection_closed = True
                except BaseException as error:
                    if self.failure is None:
                        self.failure = error

    def finish(self):
        thread, listener = self.thread, self.listener
        self.listener = None
        first = None
        try:
            if thread is not None and thread.ident is not None:
                thread.join(5.0)
                if thread.is_alive():
                    first = RuntimeError("fixture thread did not settle")
        finally:
            if listener is not None:
                try:
                    listener.close()
                    self.listener_closed = True
                except BaseException as error:
                    if first is None:
                        first = error
        if first is not None:
            raise first
        if self.failure is not None:
            raise self.failure
        if not self.listener_closed or (self.accepted and not self.connection_closed):
            raise RuntimeError("fixture cleanup incomplete")
