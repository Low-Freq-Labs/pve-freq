"""Fixed bounded profile subread plan DATA; no transport or native authority.

This plan carries no credential, TLS context, native callback or provider URL.
Only a future original owner may retain it, reserve the whole parser/wire/native
allowance, authenticate SAME result/recipient/session/source/first end and do
one fixed operation per section. Constructing/reconstructing a plan grants
nothing. Existing strict QEMU codecs define three reads; LXC is unsupported.
"""
import math

from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty
from freq.services.pilot_guest_profile_consumed import consumed_profile_guest_data_locked


class _GuestProfileSubreadsData:
    """Immutable same-context scalar plan, never an original read receipt."""
    __slots__ = ('begin', 'original', 'record', 'source', 'target', 'end',
                 'reads', 'unsupported_sections')

    def __init__(self, owner, begin, now):
        if (type(begin) is not _GuestProfileBeginDuty or begin.phase != 'spent' or
                type(begin.original) is not _OriginalRequest or
                begin.original.guest_response is not begin or
                type(begin.original.operation) is not str or
                begin.original.operation != 'guest-owner-profile' or
                begin.original.body_taken is not True or
                type(begin.values) is not tuple or len(begin.values) != 5 or
                any(type(value) is not float or not math.isfinite(value)
                    for value in (now, begin.created, begin.resource_end, begin.end,
                        begin.initial_write_end, begin.original.end,
                        begin.original.write_end)) or
                begin.resource_end != begin.created + 10.0 or
                not begin.created <= now < min(begin.end, begin.original.write_end)):
            raise _RequestUnavailable()
        record = consumed_profile_guest_data_locked(owner, begin.family,
            begin.session, begin.values[0], begin.guest_ref,
            begin.cohort, begin.generation, now)
        if (record is not begin.record or record._source is not begin.source or
                record._target is not begin.target or
                begin.family_ref != begin.family._ref or
                begin.end != min(begin.original.end, begin.initial_write_end,
                    begin.resource_end, begin.family._expires, record._expires) or
                begin.original.write_end > begin.end):
            raise _RequestUnavailable()
        node, kind, vmid = begin.target
        end = min(begin.end, begin.original.write_end)
        if kind == 'qemu':
            prefix = '/api2/json/nodes/' + node + '/qemu/' + str(vmid)
            reads = (
                ('status', 'GET', prefix + '/status/current', 262144),
                ('configured_network', 'GET', prefix + '/config', 262144),
                ('guest_network', 'GET', prefix + '/agent/network-get-interfaces', 262144),
            )
            unsupported = ()
        else:
            # The accepted wire validator requires all LXC sections unsupported.
            # Never route LXC through QEMU codecs or invent another endpoint.
            reads = ()
            unsupported = ('status', 'configured_network', 'guest_network')
        for name, value in (('begin', begin), ('original', begin.original),
                ('record', record), ('source', begin.source), ('target', begin.target),
                ('end', end), ('reads', reads),
                ('unsupported_sections', unsupported)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise TypeError('Profile subread DATA is immutable')

    def __delattr__(self, name):
        raise TypeError('Profile subread DATA is immutable')


# Per-body262144 is the existing decoder input cap, never a whole-job/RSS/
# process allowance. SAME captured end covers every sibling read and cleanup.
# No actual request serialization/credential/trust/socket/parent or callback,
# parser/formatter invocation, response admission/ACK or store/dispatch join.
