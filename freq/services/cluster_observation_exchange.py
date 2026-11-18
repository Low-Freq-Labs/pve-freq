"""Unwired fixed Cluster TCP exchange; returned bytes are provisional and private.

No credential resolver, registry issuance, provider qualification or response
admission is implemented here. Caller holds its original leases through this
exchange and the subsequent parser, cleanup and final admission boundary.
"""
import math
import time

from .cluster_observation_profile import WireTarget, serialize_request
from .cluster_observation_response import ResponseCollector
from .node_read_tls import OriginalSocket, TLSPump


NAMED_PAYLOAD_RESERVATION = 9150560


def _first_failure(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class OriginalClusterExchange:
    __slots__ = ("_socket_owner", "_busy", "_spent", "_retired",
                 "_body_failure", "_close_failure", "_clock_failure", "_failure")

    def __init__(self):
        self._socket_owner = OriginalSocket()
        self._busy = False
        self._spent = False
        self._retired = False
        # Private outside-return failure references, allocated before run.
        self._body_failure = self._close_failure = self._clock_failure = self._failure = None

    def run(self, target, private_token_components, trust_context,
            *, original_deadline):
        """Return exact body bytes or None; preserve genuine exceptions.

        The finite source fixtures supply only fictional credentials. This
        callable does not authorize credential access or a provider request.
        External invocation owner reserves NAMED_PAYLOAD_RESERVATION before
        credential resolution; failed invocations cannot refund that charge.
        Integrated callers pass the deadline captured before credential
        resolution. This exchange never creates or renews that budget. A required keyword is
        not evidence of when the caller captured it; the actual original owner
        must capture before credential/native reads and every lock wait. Native
        target/TLS owners stay retained through parsing and final publication.
        Returned full JSON body is still private, with its data envelope intact.
        """
        if self._busy or self._spent:
            self._retired = True
            return None
        self._busy = True
        self._spent = True
        original_socket_owner = self._socket_owner
        result = None
        first = None
        failed = False
        deadline = None
        try:
            now = time.monotonic()
            if (type(original_deadline) is not float
                    or not math.isfinite(original_deadline)
                    or not now < original_deadline <= now + 10.0):
                raise ValueError("cluster exchange unavailable")
            deadline = original_deadline
            if type(target) is not WireTarget:
                raise ValueError("cluster exchange unavailable")
            copied = WireTarget(target.endpoint, target.tls_name, target.node)
            request = serialize_request(copied, private_token_components)
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
            self._body_failure = error
            first = self._failure = _first_failure(first, error)
        finally:
            try:
                original_socket_owner.close()
            except BaseException as error:
                failed = True
                self._close_failure = error
                first = self._failure = _first_failure(first, error)
            # Deadline checking itself can fail in an injected fixture. It
            # cannot bypass cleanup or restore a previously failed result.
            try:
                if deadline is None or time.monotonic() >= deadline:
                    failed = True
            except BaseException as error:
                failed = True
                self._clock_failure = error
                first = self._failure = _first_failure(first, error)
            self._busy = False
        self._failure = first
        # Independent close and final clock have both been attempted. Keep
        # ordinary transport refusal as None, but preserve the actual first
        # control/MemoryError for the enclosing retained original caller.
        if first is not None and (
                not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        if (failed or self._retired
                or self._socket_owner is not original_socket_owner):
            return None
        return result
