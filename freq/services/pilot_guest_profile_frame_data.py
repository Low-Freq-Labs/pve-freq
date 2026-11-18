"""Pure supplied section-body/profile frame DATA, no original publication.

An actual original caller must retain this SAME holder before parsing/formatting
and enforce whole-job parser/wire/native allowances and earliest end. Supplied
raw bodies, observation times and an immutable plan are never private native
result receipts. Final same original writer/recipient admission remains absent.
"""
import math

from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_reference_capacity import _CapacityTicket
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData
from freq.services.guest_profile_formats.guest_status import (
    decode_guest_status, Refused as StatusRefused,
)
from freq.services.guest_profile_formats.guest_config import (
    decode_guest_config, Refused as ConfigRefused,
)
from freq.services.guest_profile_formats.guest_network import (
    decode_guest_network, Refused as NetworkRefused,
)
from freq.services.guest_profile_formats.guest_owner_wire import project_guest_owner_wire


def _inputs_data(plan, inputs):
    if type(inputs) is not tuple or len(inputs) != 3:
        raise _RequestUnavailable()
    for item in inputs:
        if type(item) is not tuple or len(item) != 2:
            raise _RequestUnavailable()
        raw, stamp = item
        if raw is None:
            if stamp is not None:
                raise _RequestUnavailable()
        elif (type(raw) is not bytes or len(raw) > 262144 or
                type(stamp) is not str or len(stamp) != 24):
            raise _RequestUnavailable()
    if plan.target[1] == 'lxc' and inputs != ((None, None),)*3:
        raise _RequestUnavailable()


class _ProfileFramePreparationData:
    """Pending same-plan frame holder, no acquiring/admission method."""
    __slots__ = ('plan', 'begin', 'end', 'inputs', 'completed_at',
                 'snapshot', 'frame', 'phase')

    def __init__(self, plan, inputs, completed_at):
        if (type(plan) is not _GuestProfileSubreadsData or
                type(plan.target) is not tuple or len(plan.target) != 3):
            raise _RequestUnavailable()
        _inputs_data(plan, inputs)
        if (type(plan.begin) is not _GuestProfileBeginDuty or
                any(type(value) is not float or not math.isfinite(value)
                    for value in (plan.end, plan.begin.original.write_end, plan.begin.created)) or
                not plan.begin.created < min(plan.end, plan.begin.original.write_end)):
            raise _RequestUnavailable()
        self.plan, self.begin = plan, plan.begin
        self.end = min(plan.end, plan.begin.original.write_end)
        self.inputs, self.completed_at = inputs, completed_at
        self.snapshot = self.frame = None
        self.phase = 'new'


def _unreported(outcome):
    return {'outcome': outcome, 'observed_at': None, 'data': None}


def prepare_profile_frame_data(duty):
    """Prepare whole canonical v2 frame once, with fixed section outcomes.

    Named bounded codec refusal makes only that QEMU section unavailable.
    Genuine controls/allocation/formatter failure propagate without retry or a
    partial response. LXC is explicitly unsupported and calls no QEMU decoder.
    Display times never renew the captured original end or prove observation.
    """
    if (type(duty) is not _ProfileFramePreparationData or duty.phase != 'new' or
            duty.frame is not None or duty.snapshot is not None or
            type(duty.plan) is not _GuestProfileSubreadsData or
            duty.begin is not duty.plan.begin or
            type(duty.begin) is not _GuestProfileBeginDuty):
        raise _RequestUnavailable()
    plan, begin = duty.plan, duty.begin
    record, family = begin.record, begin.family
    if (type(record) is not _GuestReferenceRecord or type(family) is not _GuestFamilyRecord or
            type(begin.values) is not tuple or len(begin.values) != 5 or
            plan.original is not begin.original or plan.record is not record or
            plan.source is not begin.source or plan.target is not begin.target or
            record._source is not begin.source or record._target is not begin.target or
            record._family is not family or record._session is not begin.session or
            record._principal != begin.values[0] or record._cohort is not begin.cohort or
            record._generation is not begin.generation or type(record._key) is not str or
            record._key != begin.guest_ref or type(record._purpose) is not str or
            record._purpose != 'guest' or record._spent is not True or record._retired is not False or
            type(record._ticket) is not _CapacityTicket or record._ticket._state != 'committed' or
            record._ticket._session is not begin.session or
            record._ticket._principal != begin.values[0] or
            type(record._ticket._remaining) is not int or not 1 <= record._ticket._remaining <= 256 or
            family._state != 'live' or family._ref != begin.family_ref or
            family._sources_spent is not True or
            family._session is not begin.session or family._principal != begin.values[0] or
            family._cohort is not begin.cohort or family._generation is not begin.generation or
            type(begin.source) is not tuple or len(begin.source) != 2 or
            any(type(value) is not float or not math.isfinite(value)
                for value in (duty.end, plan.end, begin.end, begin.original.write_end)) or
            duty.end > min(plan.end, begin.end, begin.original.write_end)):
        raise _RequestUnavailable()
    _inputs_data(plan, duty.inputs)
    duty.phase = 'format-attempted'  # BEFORE first parser/snapshot/wire growth.
    if plan.target[1] == 'lxc':
        status, config, network = (_unreported('unsupported'),
            _unreported('unsupported'), _unreported('unsupported'))
    else:
        status, config, network = (_unreported('unavailable'),
            _unreported('unavailable'), _unreported('unavailable'))
        raw, stamp = duty.inputs[0]
        if raw is not None:
            try:
                data = decode_guest_status(raw)
            except StatusRefused:
                pass
            else:
                status = {'outcome': 'reported', 'observed_at': stamp, 'data': data}
        raw, stamp = duty.inputs[1]
        if raw is not None:
            try:
                data = decode_guest_config(raw)
            except ConfigRefused:
                pass
            else:
                config = {'outcome': 'reported', 'observed_at': stamp, 'data': data}
        raw, stamp = duty.inputs[2]
        if raw is not None:
            try:
                data = decode_guest_network(raw)
            except NetworkRefused:
                pass
            else:
                network = {'outcome': 'reported', 'observed_at': stamp, 'data': data}
    node, kind, vmid = plan.target
    duty.snapshot = {'schema': 2, 'kind': 'guest-profile', 'owner_ref': begin.family_ref,
        'target': {'source_label': plan.source[0], 'node': node, 'guest_kind': kind,
            'vmid': vmid, 'name': None},
        'completed_at': duty.completed_at, 'status': status,
        'configured_network': config, 'guest_network': network}
    body = project_guest_owner_wire(duty.snapshot)
    duty.frame = OriginalPilotResponse(200, body, 'application/json; charset=utf-8')
    duty.phase = 'prepared'


# None name is explicit unavailable display DATA; the reference stores only the
# node/kind/VMID target, never a guessed or newly acquired name. No clock/native
# receipt/credential/whole-job allowance/ticket mutation/issuer/HTTP send/ACK.
