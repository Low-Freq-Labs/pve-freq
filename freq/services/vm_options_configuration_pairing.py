"""Options configuration/cohort integrity pairing, private supplied DATA only.

Dependencies are the unchanged accepted options codec-r7 and canonical configured
cohort types. This standalone source is not installed or imported by a route.
The future original owner must acquire/retain its own same-cohort source bytes
and derive both arguments itself. Exact types, equality and hashes below do not
prove that history, native custody, an issuer, eligibility or currentness.
"""
from dataclasses import dataclass
import hashlib
import json

from freq.services.vm_options_formats.bounded_json import CapacityExceeded, Refused
from freq.services.vm_options_formats.options_fields import decode_configuration
from freq.services.cluster_references import TargetSnapshot
from freq.services.node_read_profile import _endpoint
from freq.services.pilot_configured_cohort import PilotConfiguredData


class OptionsConfigurationMismatch(ValueError):
    def __init__(self):
        super().__init__('VM options configuration unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class OptionsConfigurationData:
    """Immutable copied scalars/bytes only; never a lease or source receipt."""
    configuration_revision: str
    configuration_bytes: bytes
    configuration_projection: str
    nodes: tuple


def pair_options_configuration_data(raw, configured):
    """Require the exact same ordered nodes in two independently parsed views.

    No missing-node/default/endpoint normalization substitution is performed.
    Literal configured endpoint spelling is conserved; normalized recipient IPs
    must also be unique. Dot-only node path segments refuse before any request.
    Revision checks are data coherence only, never generation authentication.

    This does not invoke the legacy loader, planner, registry or transport. The
    original options owner still owes acquired config projection provenance,
    purpose/credential/trust generation, first eligible template selection,
    request end and serial native duty/final-response ownership. Capacity and
    control failures retain their whole-response semantics. No parser detail or
    partial projection is returned on ordinary mismatch.
    """
    if type(raw) is not bytes or type(configured) is not PilotConfiguredData:
        raise OptionsConfigurationMismatch()
    if len(raw) > 1048576:
        raise CapacityExceeded('VM options unavailable')
    rows = configured.nodes
    revision = configured.configuration_revision
    if (type(rows) is not tuple or len(rows) > 32 or
            type(revision) is not str or not 1 <= len(revision) <= 512 or
            any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in revision)):
        raise OptionsConfigurationMismatch()
    failed = False
    try:
        nodes = []
        labels, recipients = set(), set()
        for index, row in enumerate(rows):
            if type(row) is not tuple or len(row) != 2:
                raise OptionsConfigurationMismatch()
            name, target = row
            if (type(name) is not str or not 1 <= len(name) <= 128 or
                    not name.isascii() or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-' for c in name) or
                    name in ('.', '..') or name in labels or type(target) is not TargetSnapshot):
                raise OptionsConfigurationMismatch()
            if (type(target.configuration_revision) is not str or target.configuration_revision != revision or
                    type(target.selection_key) is not str or target.selection_key != 'configured-node-' + str(index) or
                    type(target.endpoint) is not str):
                raise OptionsConfigurationMismatch()
            recipient, _version = _endpoint(target.endpoint)
            if recipient in recipients:
                raise OptionsConfigurationMismatch()
            labels.add(name)
            recipients.add(recipient)
            nodes.append((index, name, target.endpoint))
        config = decode_configuration(raw)
        if len(config['nodes']) != len(nodes):
            raise OptionsConfigurationMismatch()
        for (_, name, endpoint), public in zip(nodes, config['nodes']):
            if public['name'] != name or public['ip'] != endpoint:
                raise OptionsConfigurationMismatch()
        canonical = json.dumps(config, sort_keys=True, ensure_ascii=True,
                               allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(canonical) > 1048576:
            raise CapacityExceeded('VM options unavailable')
        projection = hashlib.sha256(canonical).hexdigest()
    except CapacityExceeded:
        raise
    except (Refused, ValueError):
        failed = True
    if failed:
        # Raise outside the parser handler; do not chain parser/source details.
        raise OptionsConfigurationMismatch()
    return OptionsConfigurationData(revision, canonical, projection, tuple(nodes))


# No original owner attachment, authorization, registry, eligibility callback,
# source acquisition, credential resolution, writer grant or serving entry.
