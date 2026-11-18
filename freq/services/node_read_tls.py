"""Unwired node TLS pump draft; no registry, credential lookup or startup hook.

The caller must reserve the reviewed payload allowance before construction.
This component does not admit a result to a session or establish authority.
"""
import math
import socket
import ssl
import time

from .node_read_profile import WireTarget


CHUNK = 16384
PENDING = 65536
INBOUND = 2097152
OUTBOUND = 262144
STEPS = 4096


def _refuse():
    raise ValueError("node TLS unavailable")


class OriginalSocket:
    """One retained original descriptor duty, never physical closure proof.

    Pending state precedes the sole constructor/close call. Known returned
    handle stays strongly retained even after close returns or raises. Unknown
    constructor return without a saved handle remains outside-parent custody;
    it cannot be retried or reported as a resource-free close. These local
    states do not classify a lost successful return at the outer caller seam.
    Original once-attempt/job owners must retain their own pending obligations.
    """

    __slots__ = ("_socket", "_spent", "_acquisition", "_closure")

    def __init__(self):
        self._socket = None
        self._spent = False
        self._acquisition = 'unstarted'
        self._closure = 'unattempted'

    def acquire(self, version):
        if (self._spent or self._acquisition != 'unstarted' or
                self._socket is not None or self._closure != 'unattempted'):
            _refuse()
        if type(version) is not int or version not in (4, 6):
            _refuse()
        self._acquisition = 'acquire-pending'  # BEFORE constructor/unknown return.
        self._socket = socket.socket(
            socket.AF_INET if version == 4 else socket.AF_INET6,
            socket.SOCK_STREAM,
        )
        self._acquisition = 'owned'

    def close(self):
        if self._closure in ('returned', 'returned-no-acquisition'):
            return  # No second native close, not a whole-job completion grant.
        if self._closure != 'unattempted':
            _refuse()  # Pending/unknown close must never be retried.
        self._spent = True  # Veto acquisition and pump progress before effects.
        original = self._socket
        if original is None:
            if self._acquisition != 'unstarted':
                self._closure = 'uncertain-acquisition'
                _refuse()
            self._closure = 'returned-no-acquisition'
            return
        if self._acquisition not in ('acquire-pending', 'owned'):
            self._closure = 'uncertain-state'
            _refuse()
        self._closure = 'close-pending'  # BEFORE sole close; no catch/reset.
        original.close()
        self._closure = 'returned'
        # Never clear _socket. Known handle and pending acquisition state stay
        # retained; a returned local close is not physical/job/recipient proof.


class TLSPump:
    """Cooperative absolute-deadline pump over one externally cleaned owner.

    Caller must close the original owner even if construction or connect fails.
    Trust context is externally owned and must stay immutable for the lease.
    Counters never refund on failure. No chunk history or diagnostic is stored.
    """

    __slots__ = (
        "owner", "deadline", "incoming", "outgoing", "tls",
        "received", "sent", "steps", "target",
    )

    def __init__(self, owner, context, target, deadline):
        if type(owner) is not OriginalSocket or type(target) is not WireTarget:
            _refuse()
        if type(context) is not ssl.SSLContext:
            _refuse()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            _refuse()
        if type(deadline) is not float or not math.isfinite(deadline):
            _refuse()
        self.owner = owner
        self.target = WireTarget(target.endpoint, target.tls_name, target.node)
        self.deadline = deadline
        self.received = 0
        self.sent = 0
        self.steps = 0
        self.incoming = ssl.MemoryBIO()
        self.outgoing = ssl.MemoryBIO()
        # SSLObject has no descriptor. No TCP effect precedes this allocation.
        self.tls = context.wrap_bio(
            self.incoming, self.outgoing,
            server_side=False, server_hostname=self.target.tls_name,
        )
        self._boundary()

    def _boundary(self):
        self.steps += 1
        remaining = self.deadline - time.monotonic()
        if self.steps > STEPS or remaining <= 0:
            _refuse()
        if self.incoming.pending > PENDING or self.outgoing.pending > PENDING:
            _refuse()
        if self.owner._spent:
            _refuse()
        return remaining

    def connect(self):
        target = self.target
        self._boundary()
        self.owner.acquire(target.address_version)
        original = self.owner._socket
        original.settimeout(self._boundary())
        original.connect((target.endpoint, 8006))
        self._boundary()
        while True:
            try:
                self._boundary()
                self.tls.do_handshake()
                self._boundary()
                self._drain()
                return
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                if not self._drain():
                    _refuse()

    def _drain(self):
        progressed = False
        self._boundary()
        while self.outgoing.pending:
            size = min(CHUNK, self.outgoing.pending)
            if self.sent + size > OUTBOUND:
                _refuse()
            # Charge before taking a copy. Partial send failure never refunds.
            self.sent += size
            data = self.outgoing.read(size)
            self._boundary()
            original = self.owner._socket
            original.settimeout(self._boundary())
            original.sendall(data)
            self._boundary()
            progressed = True
        return progressed

    def _receive(self):
        self._drain()
        remaining = INBOUND - self.received
        if remaining <= 0:
            _refuse()
        original = self.owner._socket
        original.settimeout(self._boundary())
        data = original.recv(min(CHUNK, remaining))
        self.received += len(data)
        self._boundary()
        if not data or self.incoming.pending + len(data) > PENDING:
            _refuse()
        accepted = self.incoming.write(data)
        if accepted != len(data):
            _refuse()
        self._boundary()

    def write_request(self, request):
        if type(request) is not bytes or not 1 <= len(request) <= 4096:
            _refuse()
        offset = 0
        while offset < len(request):
            try:
                self._boundary()
                count = self.tls.write(memoryview(request)[offset:])
                self._boundary()
                if not 0 < count <= len(request) - offset:
                    _refuse()
                offset += count
                self._drain()
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                if not self._drain():
                    _refuse()

    def read(self, maximum):
        if type(maximum) is not int or not 1 <= maximum <= CHUNK:
            _refuse()
        while True:
            try:
                self._boundary()
                data = self.tls.read(maximum)
                self._boundary()
                self._drain()
                if not data:
                    _refuse()
                return data
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                if not self._drain():
                    _refuse()
