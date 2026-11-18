"""Unwired original TCP exchange; returned bytes are provisional and private.

No credential resolver, registry issuance, provider qualification or response
admission is implemented here. Caller holds its original leases through this
exchange and the subsequent parser, cleanup and final admission boundary.
"""
import math
import time

from .node_read_profile import WireTarget, serialize_request
from .node_read_response import ResponseCollector
from .node_read_tls import OriginalSocket, TLSPump


NAMED_PAYLOAD_RESERVATION = 9150560


class OriginalExchange:
    __slots__ = ("_socket_owner", "_busy", "_spent", "_retired")

    def __init__(self):
        self._socket_owner = OriginalSocket()
        self._busy = False
        self._spent = False
        self._retired = False

    def run(self, target, fictional_or_authorized_credentials, trust_context,
            *, original_deadline=None):
        """Return exact body bytes or None; preserve genuine exceptions.

        The development harness supplies only fictional credentials. This
        callable does not authorize credential access or a provider request.
        External invocation owner reserves NAMED_PAYLOAD_RESERVATION before
        credential resolution; failed invocations cannot refund that charge.
        Integrated callers pass the deadline captured before credential
        resolution. This exchange may shorten but never renew that budget.
        """
        if self._busy or self._spent:
            self._retired = True
            return None
        self._busy = True
        self._spent = True
        original_socket_owner = self._socket_owner
        result = None
        first_genuine = None
        failed = False
        deadline = None
        try:
            now = time.monotonic()
            if original_deadline is None:
                deadline = now + 10.0
            else:
                if (type(original_deadline) is not float
                        or not math.isfinite(original_deadline)
                        or not now < original_deadline <= now + 10.0):
                    raise ValueError("node exchange unavailable")
                deadline = original_deadline
            if type(target) is not WireTarget:
                raise ValueError("node exchange unavailable")
            copied = WireTarget(target.endpoint, target.tls_name, target.node)
            request = serialize_request(copied, fictional_or_authorized_credentials)
            collector = ResponseCollector()
            pump = TLSPump(original_socket_owner, trust_context, copied, deadline)
            pump.connect()
            pump.write_request(request)
            while True:
                maximum = collector.next_read_size()
                if maximum == 0:
                    break
                collector.feed(pump.read(maximum))
            result = collector.finish()
            if time.monotonic() >= deadline:
                failed = True
        except BaseException as error:
            failed = True
            if not isinstance(error, Exception):
                first_genuine = error
        finally:
            try:
                original_socket_owner.close()
            except BaseException as error:
                failed = True
                if first_genuine is None and not isinstance(error, Exception):
                    first_genuine = error
            # Deadline checking itself can fail in an injected fixture. It
            # cannot bypass cleanup or restore a previously failed result.
            try:
                if deadline is None or time.monotonic() >= deadline:
                    failed = True
            except BaseException as error:
                failed = True
                if first_genuine is None and not isinstance(error, Exception):
                    first_genuine = error
            self._busy = False
        if first_genuine is not None:
            raise first_genuine
        if (failed or self._retired
                or self._socket_owner is not original_socket_owner):
            return None
        return result
