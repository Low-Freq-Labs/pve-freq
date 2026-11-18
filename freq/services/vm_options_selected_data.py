"""Private optional-source selection, not native absence or original authority.

None and derived source-kind strings describe caller DATA only. The actual
original owner still owes its exact retained native presence/absence and source,
code, principal, namespace, writer, purpose, generation, end and physical duties.
No source document is rewritten, no file/profile bytes are fabricated for inline
configuration, and no bootstrap/full11/public response/eligibility is created.
"""
from dataclasses import dataclass
import tomllib

from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.vm_options_formats.bounded_json import CapacityExceeded, Refused
from freq.services.vm_options_formats.options_fields import token
from freq.services.vm_options_base_data import project_options_base_data
from freq.services.vm_options_catalog_data import project_options_catalog_data
from freq.services.vm_options_network_data import (
    OptionsNetworkData, _project_network_values,
)
from freq.services.vm_options_prepared_fields import (
    OptionsPreparedFieldsData, _collect, _FIELDS,
)


class OptionsSelectionUnavailable(ValueError):
    def __init__(self):
        super().__init__('VM options source selection unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class SelectedOptionsNetworkData:
    profile_source_kind: str
    data: OptionsNetworkData


@dataclass(frozen=True, slots=True, repr=False)
class SelectedOptionsPreparedFieldsData:
    catalog_source_kind: str
    profile_source_kind: str
    prepared: OptionsPreparedFieldsData


def _need(condition):
    if not condition:
        raise OptionsSelectionUnavailable()


def _inline_entries(inline):
    """Exact parsed TOML dictionaries only; no default/coercion/alias choice."""
    _need(type(inline) is dict)
    if len(inline) > 128:
        raise CapacityExceeded('VM options unavailable')
    profiles = []
    for key, info in inline.items():
        identity = token(key)
        _need(type(info) is dict)
        row = dict(id=identity)
        for field in ('name', 'vlan', 'bridge', 'purpose', 'description', 'gateway_role'):
            row[field] = info[field]
        for alias in ('id', 'key'):
            if alias in info:
                _need(type(info[alias]) is str and info[alias] == identity)
        if 'vlan_id' in info:
            _need(type(info['vlan_id']) is int and type(row['vlan']) is int and
                  info['vlan_id'] == row['vlan'])
        # Complete scalar/schema/reference/association validation is shared
        # with the original present-file profile below, without copying extras.
        profiles.append(row)
    return profiles


def project_selected_options_network_data(freq_raw, vlan_raw, profile_raw):
    """Select private explicit inline/empty only for optional None-shaped DATA.

Present bytes, including empty, never fall back to inline configuration. This
function does not authenticate None, prove native absence, create a receipt or
release any original acquisition duty. Logical raw/row/output limits are not
runtime/heap/traceback/native physical containment.
"""
    if (type(freq_raw) is not bytes or type(vlan_raw) is not bytes or
            profile_raw is not None and type(profile_raw) is not bytes):
        raise OptionsSelectionUnavailable()
    raws = (freq_raw, vlan_raw) if profile_raw is None else (freq_raw, vlan_raw, profile_raw)
    if any(len(raw) > 1048576 for raw in raws) or sum(map(len, raws)) > 3145728:
        raise CapacityExceeded('VM options unavailable')
    failed = False
    try:
        f, v = (tomllib.loads(raw.decode('utf-8', 'strict')) for raw in (freq_raw, vlan_raw))
        nic = f['nic']
        _need(type(nic) is dict)
        inline = nic.get('profiles', {})
        _need(type(inline) is dict)
        if profile_raw is not None:
            _need(not inline)
            p = tomllib.loads(profile_raw.decode('utf-8', 'strict'))
            profiles = p.get('profile', [])
            kind = 'present-file'
        elif inline:
            profiles = _inline_entries(inline)
            kind = 'absent-inline'
        else:
            profiles = []
            kind = 'absent-empty'
        data = _project_network_values(f, v, profiles)
    except CapacityExceeded:
        raise
    except (Refused, ValueError, KeyError, RecursionError):
        failed = True
    if failed:
        raise OptionsSelectionUnavailable()
    return SelectedOptionsNetworkData(kind, data)


def prepare_selected_options_fields_data(freq_raw, distro_raw, vlan_raw, profile_raw, configured):
    """Fixed base/catalog/selected-network, same original freq argument once.

First public component failure propagates unchanged and stops later components.
Private source labels grant no native observation or source authority. Reuse the
canonical ten-piece framing budget; a future genuine bootstrap must separately
account/validate complete11 bytes. No hash, wire or OptionsConfigurationData.
"""
    if (type(freq_raw) is not bytes or type(vlan_raw) is not bytes or
            any(raw is not None and type(raw) is not bytes for raw in (distro_raw, profile_raw)) or
            type(configured) is not PilotConfiguredData):
        raise OptionsSelectionUnavailable()
    raws = tuple(raw for raw in (freq_raw, distro_raw, vlan_raw, profile_raw) if raw is not None)
    if any(len(raw) > 1048576 for raw in raws) or sum(map(len, raws)) > 4194304:
        raise CapacityExceeded('VM options unavailable')
    parts, used = {}, 2
    base = project_options_base_data(freq_raw, configured)
    used = _collect(parts, base.field_bytes, used)
    catalog = project_options_catalog_data(b'' if distro_raw is None else distro_raw)
    used = _collect(parts, (('distros', catalog.catalog_bytes),), used)
    network = project_selected_options_network_data(freq_raw, vlan_raw, profile_raw)
    used = _collect(parts, network.data.field_bytes, used)
    _need(set(parts) == set(_FIELDS))
    prepared = OptionsPreparedFieldsData(base.configuration_revision, base.nodes,
                                         base.service_account,
                                         tuple((key, parts[key]) for key in _FIELDS), used)
    return SelectedOptionsPreparedFieldsData('absent' if distro_raw is None else 'present-file',
                                             network.profile_source_kind, prepared)


# No source path/IO/legacy loader/provider/credential/key/bootstrap/full11/public
# response, authority flag, native factory, request admission or activation.
