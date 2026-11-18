"""WIP private once-section exchange; no original issuer or native grant.

Requires the separately reviewed retained OriginalSocket custody correction.
Actual original registered-profile parent must own whole-job aggregate native,
credential/trust/parser/wire lifetime BEFORE constructing/calling this holder.
No such actual owner is supplied by this module. Store/dispatcher stay unwired.
"""
import math
import threading
import time

from freq.services.node_read_profile import WireTarget
from freq.services.node_read_tls import OriginalSocket, TLSPump
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData
from freq.services.pilot_guest_profile_wire import serialize_profile_section_request
from freq.services.pilot_guest_profile_response import ProfileSectionResponseCollector


def _refuse():
    raise ValueError('Guest profile section exchange unavailable')


def _priority(error):
    if not issubclass(type(error), Exception):
        return 2
    return 1 if issubclass(type(error), MemoryError) else 0


def _first(first, later):
    if first is None or _priority(later) > _priority(first):
        return later
    return first


class _ProfileSectionExchange:
    """Retained provisional private body and native local cleanup obligations.

    Outer original parent must pre-retain this SAME holder before constructor
    or run boundaries. Local prepared/returned states are DATA only: a lost
    successful run return must remain pending/uncertain at that outside parent.
    No method here permits retry, authenticates source/result or final recipient,
    settles aggregate physical duties or admits a response.
    """
    __slots__ = ('_plan', '_section', '_end', '_last_clock', '_thread', '_socket_owner',
                 '_original_socket', '_collector', '_pump', '_credentials',
                 '_trust', '_request', '_last_chunk', '_result', '_operation',
                 '_phase', '_cleanup', '_failure', '_body_failure',
                 '_cleanup_failure', '_late_failure')

    def __init__(self, plan, section, *, original_deadline):
        if (type(plan) is not _GuestProfileSubreadsData or type(section) is not str or
                section not in ('status', 'configured_network', 'guest_network') or
                type(original_deadline) is not float or not math.isfinite(original_deadline) or
                type(plan.end) is not float or not math.isfinite(plan.end) or
                type(plan.target) is not tuple or len(plan.target) != 3 or
                type(plan.target[1]) is not str or plan.target[1] != 'qemu' or
                type(plan.reads) is not tuple or len(plan.reads) != 3 or
                type(plan.unsupported_sections) is not tuple or plan.unsupported_sections != () or
                original_deadline > plan.end):
            _refuse()
        self._plan, self._section, self._end = plan, section, original_deadline
        self._last_clock = None
        self._thread = threading.current_thread()
        self._socket_owner = self._original_socket = None
        self._collector = self._pump = self._credentials = self._trust = None
        self._request = self._last_chunk = self._result = self._failure = None
        self._body_failure = self._cleanup_failure = self._late_failure = None
        self._operation, self._phase, self._cleanup = 'constructor-pending', 'constructor-pending', 'unattempted'
        owner = OriginalSocket()  # Corrected constructor has pure fields only.
        self._socket_owner = self._original_socket = owner
        # Fail closed if composed accidentally with the older unsafe class.
        # Field presence is compatibility DATA, never native owner authority.
        if (type(owner) is not OriginalSocket or
                getattr(owner, '_acquisition', None) != 'unstarted' or
                getattr(owner, '_closure', None) != 'unattempted' or owner._spent is not False):
            _refuse()
        self._operation, self._phase = 'constructor-returned', 'new'

    def _same_original_socket(self):
        if (threading.current_thread() is not self._thread or
                type(self._original_socket) is not OriginalSocket):
            _refuse()
        return self._original_socket

    def _remaining(self):
        now = time.monotonic()
        if (type(now) is not float or not math.isfinite(now) or
                type(self._end) is not float or not math.isfinite(self._end) or
                not now < self._end or self._last_clock is not None and
                (type(self._last_clock) is not float or not math.isfinite(self._last_clock) or now < self._last_clock)):
            _refuse()
        self._last_clock = now
        return self._end - now

    def retire(self):
        """Sole known socket close; retain everything, no physical receipt.

        Pending/unknown close never retries. Known returned close is locally
        idempotent and cannot resolve an outside parent's lost return. Even
        source-owner replacement cannot redirect the close from saved owner.
        """
        original = self._same_original_socket()
        if self._phase == 'new':
            self._phase = 'retired'
        if self._cleanup == 'returned':
            if self._socket_owner is not original:
                _refuse()
            return
        if self._cleanup != 'unattempted':
            _refuse()
        self._cleanup = 'close-pending'
        original.close()
        self._cleanup = 'returned'
        if self._socket_owner is not original:
            _refuse()
        # Do not clear handle, pump, collector, private credentials/request/body
        # or failure. Original outside custody/allowance still owns all of it.

    def run(self, transport, private_credentials, trust_context):
        """One provisional exchange only, preserves genuine controls.

        None means only local failure, never a section-unavailable grant.
        MemoryError and genuine controls propagate after independent cleanup.
        Outer original caller must first validate SAME registered context,
        source/token/trust/result duty and preown native aggregate allowances.
        Inputs and local class/flag identities cannot grant those rights.
        There is no fresh or renewable deadline or implicit retry here.
        """
        original = self._same_original_socket()
        if (self._phase != 'new' or self._cleanup != 'unattempted' or
                self._socket_owner is not original or original._spent is not False):
            _refuse()
        self._phase = 'run-pending'  # BEFORE every fallible/acquiring boundary.
        first = None
        try:
            remaining = self._remaining()
            if remaining > 10.0 or type(transport) is not WireTarget:
                _refuse()
            self._credentials, self._trust = private_credentials, trust_context
            self._operation = 'serialize-pending'
            self._request = serialize_profile_section_request(
                self._plan, self._section, transport, self._credentials)
            self._operation = 'serialize-returned'
            self._remaining()
            # Pre-publish pure object storage before constructors grow header
            # or BIO/TLS state. Unknown allocation returns still belong to the
            # preowned original whole-job parent, not a made-up local receipt.
            self._operation = 'collector-constructor-pending'
            self._collector = ProfileSectionResponseCollector.__new__(ProfileSectionResponseCollector)
            ProfileSectionResponseCollector.__init__(self._collector)
            self._operation = 'collector-constructor-returned'
            self._remaining()
            self._operation = 'pump-constructor-pending'
            self._pump = TLSPump.__new__(TLSPump)
            TLSPump.__init__(self._pump, original, self._trust, transport, self._end)
            self._operation = 'pump-constructor-returned'
            self._operation = 'connect-pending'
            self._pump.connect()
            self._operation = 'connect-returned'
            self._operation = 'write-pending'
            self._pump.write_request(self._request)
            self._operation = 'write-returned'
            while True:
                self._remaining()
                self._operation = 'size-pending'
                maximum = self._collector.next_read_size()
                self._operation = 'size-returned'
                if type(maximum) is not int or not 0 <= maximum <= 16384:
                    _refuse()
                if maximum == 0:
                    break
                self._operation = 'read-pending'
                self._last_chunk = self._pump.read(maximum)
                self._operation = 'read-returned'
                if type(self._last_chunk) is not bytes or not 1 <= len(self._last_chunk) <= maximum:
                    _refuse()
                self._operation = 'feed-pending'
                self._collector.feed(self._last_chunk)
                self._operation = 'feed-returned'
            self._operation = 'finish-pending'
            self._result = self._collector.finish()  # Retain BEFORE clock/close/return.
            self._operation = 'finish-returned'
            if type(self._result) is not bytes or not 1 <= len(self._result) <= 262144:
                _refuse()
            self._remaining()
        except BaseException as error:
            self._body_failure = error
            first = error
        finally:
            # Independent close before any late clock; no earlier body/control
            # can skip it. Saved original owner is never replaced by an argument.
            try:
                self.retire()
            except BaseException as cleanup:
                self._cleanup_failure = cleanup
                first = _first(first, cleanup)
            try:
                self._remaining()
            except BaseException as late:
                self._late_failure = late
                first = _first(first, late)
        self._failure = first
        if first is not None:
            self._phase = 'failed'
            if _priority(first) > 0:
                raise first
            return None
        if (self._socket_owner is not original or self._cleanup != 'returned' or
                type(self._result) is not bytes):
            self._phase = 'failed'
            return None
        self._phase = 'prepared'
        return self._result  # Provisional private bytes, no original result grant.


# WIP only. No credential resolver, original profile slot/caller/retirement
# joining, source/result receipt, decoder/frame, recipient admission or ACK.
