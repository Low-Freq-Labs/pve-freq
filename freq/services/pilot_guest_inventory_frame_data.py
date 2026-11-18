"""Fixed whole inventory success frame DATA, never original publication.

Original caller must retain this holder before formatting outside its guards,
under separate parser/child/wire and physical allowances. Source/candidates and
display times here are DATA; prepared bytes neither issue references nor admit
a response. The SAME original final writer must later revalidate its complete
source/request/session/family/recipient/end and once-write this exact frame.
"""
from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.pilot_guest_inventory_children_data import (
    _InventoryGuestBatchData, prepared_inventory_guest_records_data,
)
from freq.services.guest_profile_formats.guest_owner_wire import project_guest_owner_wire


class _InventoryFramePreparationData:
    """Pure pending original-shaped frame holder, not admission authority."""
    __slots__ = ('batch', 'begin', 'end', 'observed_at', 'completed_at', 'frame', 'phase')

    def __init__(self, batch, observed_at, completed_at):
        if type(batch) is not _InventoryGuestBatchData:
            raise _RequestUnavailable()
        self.batch, self.begin, self.end = batch, batch.begin, batch.begin.end
        self.observed_at, self.completed_at = observed_at, completed_at
        self.frame = None
        self.phase = 'new'


def prepare_inventory_frame_data(duty):
    """Prepare SAME whole canonical schema-two frame once, no partial rows.

    No clock or acquisition runs here. Display timestamp ordering is not an
    authority/freshness/deadline claim. Zero guest DATA does not settle its
    explicit original ticket; the enclosing original transaction still owes it.
    """
    if (type(duty) is not _InventoryFramePreparationData or duty.phase != 'new' or
            duty.frame is not None or type(duty.batch) is not _InventoryGuestBatchData or
            duty.begin is not duty.batch.begin or duty.end != duty.begin.end):
        raise _RequestUnavailable()
    batch = duty.batch
    prepared_inventory_guest_records_data(batch)
    source = duty.begin.source
    if (type(source) is not tuple or len(source) != 2 or
            type(duty.begin.family_ref) is not str or
            duty.begin.family_ref != duty.begin.family._ref):
        raise _RequestUnavailable()
    duty.phase = 'format-attempted'  # BEFORE payload growth/serialization.
    guests = []
    for row, record in zip(batch.decoded.rows, batch.records):
        guests.append({'guest_ref': record._key, 'node': row[0],
            'guest_kind': row[1], 'vmid': row[2], 'name': row[3]})
    body = project_guest_owner_wire({'schema': 2, 'kind': 'guest-inventory',
        'owner_ref': duty.begin.family_ref, 'source_label': source[0],
        'observed_at': duty.observed_at, 'completed_at': duty.completed_at,
        'guests': guests})
    duty.frame = OriginalPilotResponse(200, body, 'application/json; charset=utf-8')
    duty.phase = 'prepared'


# No ticket commit/index/refund, entropy, reference issuance, HTTP reservation,
# source/native grant, send/ACK, original store/dispatch join or activation.
