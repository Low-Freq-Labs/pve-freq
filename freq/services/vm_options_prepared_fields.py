"""Ten private options pieces from shared inputs; bootstrap remains unavailable.

No complete public configuration, hash, envelope, source receipt or authority
is created. The eventual original owner still owes acquisition, same-source
history, writer/code/principal/purpose/generation/end/physical duty custody and
genuine key metadata. Equality/shared arguments are pure DATA relationships.
"""
from dataclasses import dataclass

from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.vm_options_formats.bounded_json import CapacityExceeded
from freq.services.vm_options_base_data import project_options_base_data
from freq.services.vm_options_catalog_data import project_options_catalog_data
from freq.services.vm_options_network_data import project_options_network_data


_FIELDS = ('nodes', 'storage', 'distros', 'vlans', 'network_profiles',
           'network_policy', 'cpu', 'memory', 'lifecycle', 'disk')


class OptionsPreparationUnavailable(ValueError):
    def __init__(self):
        super().__init__('VM options preparation unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class OptionsPreparedFieldsData:
    """Private ten pieces only, no bootstrap or full configuration bytes."""
    configuration_revision: str
    nodes: tuple
    service_account: str
    field_bytes: tuple
    accounted_partial_object_bytes: int


def _collect(parts, entries, used):
    """Charge private piece bytes and complete ten-field JSON framing.

Only fixed projection returns reach this helper, never an externally supplied
partial record. Exact primitive checks also prevent accidental hooks/duplicates.
This count is not a final eleven-field output allowance: a future owner must
account and validate the complete object again after genuine bootstrap exists.
"""
    if type(entries) is not tuple:
        raise OptionsPreparationUnavailable()
    for entry in entries:
        if type(entry) is not tuple or len(entry) != 2:
            raise OptionsPreparationUnavailable()
        name, raw = entry
        if type(name) is not str or name not in _FIELDS or name in parts or type(raw) is not bytes:
            raise OptionsPreparationUnavailable()
        # Trusted field names are ASCII: quotes + colon, plus optional comma.
        used += len(name) + 3 + len(raw) + bool(parts)
        if used > 1048576:
            raise CapacityExceeded('VM options unavailable')
        parts[name] = raw
    return used


def prepare_options_fields_data(freq_raw, distro_raw, vlan_raw, profile_raw, configured):
    """Invoke fixed private projections once in base/catalog/network order.

The exact same immutable freq argument reaches both base and network paths;
callers cannot substitute independently prepared partial records or callbacks.
Each input <=1MiB and four-input aggregate <=4MiB are logical private limits,
not authorization to extend the original reader or physical memory/time bounds.

Charge each returned component before calling the next. Any exception escapes
unchanged and stops subsequent work, preserving first ordinary/capacity/memory/
control identity without diagnostics, fallback, retry or partial success. Raw
buffers, intermediate values and failures still need the original qualified
supervised worker/lifetime/resource owner; no secure erasure is claimed.
"""
    raws = (freq_raw, distro_raw, vlan_raw, profile_raw)
    if any(type(raw) is not bytes for raw in raws) or type(configured) is not PilotConfiguredData:
        raise OptionsPreparationUnavailable()
    if any(len(raw) > 1048576 for raw in raws) or sum(map(len, raws)) > 4194304:
        raise CapacityExceeded('VM options unavailable')
    parts, used = {}, 2  # Count braces even though no partial object is emitted.
    base = project_options_base_data(freq_raw, configured)
    used = _collect(parts, base.field_bytes, used)
    catalog = project_options_catalog_data(distro_raw)
    used = _collect(parts, (('distros', catalog.catalog_bytes),), used)
    network = project_options_network_data(freq_raw, vlan_raw, profile_raw)
    used = _collect(parts, network.field_bytes, used)
    if set(parts) != set(_FIELDS):
        raise OptionsPreparationUnavailable()
    return OptionsPreparedFieldsData(base.configuration_revision, base.nodes,
                                     base.service_account,
                                     tuple((key, parts[key]) for key in _FIELDS), used)


# The future genuine bootstrap/full11 decoder/pairing, source/admission/public
# emission and original form-recipient joins are deliberately still absent.
