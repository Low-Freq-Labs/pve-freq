"""Private retained-freq options pieces. Supplied DATA, never source authority.

This implements only the six complete base field pieces in CONTRACT-R2. The
original owner must acquire and retain the bytes, code/principal/writer cohort,
deadline and resource duties itself. No path, loader, provider, key probe, native
callback, route or issuer is accepted here. Counts do not bound physical parser
memory, runtime or retained tracebacks. The remaining five configuration fields
and genuine key metadata must exist before any complete public projection.
"""
from dataclasses import dataclass
import json
import tomllib

from freq.services.cluster_references import TargetSnapshot
from freq.services.node_read_profile import _endpoint
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_readonly_inputs import PilotInputUnavailable, _user
from freq.services.vm_options_formats.bounded_json import CapacityExceeded, Refused
from freq.services.vm_options_formats.options_fields import grammar, token
from freq.services.vm_options_formats.wire_schema import SCHEMA


_LIMIT = 1048576
_FIELDS = ('nodes', 'storage', 'cpu', 'memory', 'lifecycle', 'disk')


class OptionsBaseUnavailable(ValueError):
    def __init__(self):
        super().__init__('VM options base unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class OptionsBaseData:
    """Copied immutable pieces, not full configuration, lease or receipt."""
    configuration_revision: str
    nodes: tuple
    pools: tuple
    field_bytes: tuple
    service_account: str


def _need(condition):
    if not condition:
        raise OptionsBaseUnavailable()


def _table(parent, key):
    value = parent[key]
    _need(type(value) is dict)
    return value


def project_options_base_data(retained_freq_bytes, configured_data):
    """Pair explicit original-file metadata with a canonical configured view.

Both arguments remain caller-constructible; equality is data coherence only.
Missing required defaults/service/node arrays refuse this narrower profile.
Missing storage means known zero *configured declarations*, never a provider
observation or fallback. Literal endpoint spelling/order is conserved while
normalized duplicate recipients refuse. Shared pool IDs on different nodes are
distinct. No malformed row is filtered and no partial result escapes failure.

An ordinary failure is raised outside the parser handler without parser text or
chained source diagnostics. Capacity, MemoryError and control exceptions retain
their whole-response priority and identity; source may remain in those frames.
"""
    if type(retained_freq_bytes) is not bytes or type(configured_data) is not PilotConfiguredData:
        raise OptionsBaseUnavailable()
    if len(retained_freq_bytes) > _LIMIT:
        raise CapacityExceeded('VM options unavailable')
    rows = configured_data.nodes
    revision = configured_data.configuration_revision
    service = configured_data.service_user
    if (type(rows) is not tuple or len(rows) > 32 or
            type(revision) is not str or not 1 <= len(revision) <= 512 or
            any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in revision)):
        raise OptionsBaseUnavailable()
    failed = False
    try:
        document = tomllib.loads(retained_freq_bytes.decode('utf-8', 'strict'))
        pve = _table(document, 'pve')
        defaults = _table(_table(document, 'vm'), 'defaults')
        ssh = _table(document, 'ssh')
        endpoints, labels = pve['nodes'], pve['node_names']
        _need(type(endpoints) is list and type(labels) is list)
        _need(len(endpoints) == len(labels) == len(rows))
        explicit_service = ssh['service_account']
        _user(explicit_service, 'viewer')
        _need(type(service) is str and explicit_service == service)
        storage = pve.get('storage', {})
        _need(type(storage) is dict and len(storage) <= 32)
        names, recipients, immutable_nodes, immutable_pools = set(), set(), [], []
        nodes, pools, by_node = [], [], {}
        for index, row in enumerate(rows):
            _need(type(row) is tuple and len(row) == 2)
            name, target = row
            token(name)
            _need(name not in ('.', '..') and name not in names)
            _need(type(target) is TargetSnapshot)
            _need(type(target.configuration_revision) is str and target.configuration_revision == revision)
            _need(type(target.selection_key) is str and target.selection_key == 'configured-node-' + str(index))
            _need(type(target.endpoint) is str)
            recipient, _version = _endpoint(target.endpoint)
            _need(recipient not in recipients)
            _need(type(labels[index]) is str and labels[index] == name)
            _need(type(endpoints[index]) is str and endpoints[index] == target.endpoint)
            names.add(name)
            recipients.add(recipient)
            entry = storage.get(name, {})
            _need(type(entry) is dict)
            pool, kind = entry.get('pool', ''), entry.get('type', '')
            # Even an empty declaration must not conceal malformed metadata.
            _need(type(pool) is str and type(kind) is str)
            grammar(kind, SCHEMA['$defs']['storage']['properties']['type'])
            if pool:
                token(pool)
                pools.append(dict(id=pool, label=pool, node=name, type=kind,
                                  source='configured', availability='unknown'))
                immutable_pools.append((name, pool, kind))
            by_node[name] = pool
            immutable_nodes.append((index, name, target.endpoint, pool))
            nodes.append(dict(name=name, ip=target.endpoint, storage=pool,
                              default=index == 0, source='configured', availability='unknown'))
        _need(all(name in names for name in storage))
        # Fixed schema literals are presentation metadata, never capabilities.
        pieces = dict(nodes=nodes, storage=pools,
                      cpu=dict(default=defaults['cpu'], choices=list(SCHEMA['properties']['cpu']['properties']['choices']['const'])),
                      memory=dict(default_mb=defaults['ram'], ballooning_default=True),
                      lifecycle=dict(start_on_boot_default=False, accepted_keys=['onboot', 'start_on_boot']),
                      disk=dict(default_gb=defaults['disk'], default_storage=pools[0]['id'] if pools else None,
                                default_by_node=by_node))
        encoded, total = [], 0
        for field in _FIELDS:
            grammar(pieces[field], SCHEMA['properties'][field])
            raw = json.dumps(pieces[field], sort_keys=True, ensure_ascii=True,
                             allow_nan=False, separators=(',', ':')).encode('utf-8')
            total += len(raw)
            if total > _LIMIT:
                raise CapacityExceeded('VM options unavailable')
            encoded.append((field, raw))
    except CapacityExceeded:
        raise
    except (PilotInputUnavailable, Refused, ValueError, KeyError, RecursionError):
        failed = True
    if failed:
        raise OptionsBaseUnavailable()
    return OptionsBaseData(revision, tuple(immutable_nodes), tuple(immutable_pools),
                           tuple(encoded), service)


# No complete configuration, bootstrap, digest, public envelope, route, source
# attachment, original acquisition, generation or positive admission is issued.
