"""Pure metadata projection; no source completeness or authority is conferred.

Caller supplies exactly three retained byte strings. Installed generation capture,
authorization, revision identity, artifact publication and download are separate.
"""
import tomllib

from . import config_export_artifact as codec

FILES = frozenset(('freq.toml', 'hosts.toml', 'vlans.toml'))
FILE_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 4 * 1024 * 1024
REFUSAL = 'Configuration metadata source unavailable'


class ProjectionRefused(ValueError):
    """Fixed message; never includes source bytes, parser errors or paths."""


def _require(condition):
    if not condition:
        raise ProjectionRefused(REFUSAL)


def _groups(value):
    _require(type(value) is str and len(value) <= 128 * 129)
    if value == '':
        return []
    groups = value.split(',')
    _require(len(groups) <= 128 and len(set(groups)) == len(groups))
    for group in groups:
        _require(bool(group) and group == group.strip() and len(group) <= 128)
    return sorted(groups)


def project(sources):
    """Return a fresh deterministic codec-compatible metadata payload.

    Required empties: hosts `host=[]`, VLANs `[vlan]`, frequency `[pve] nodes=[]`
    and `[infrastructure] cluster_name=""`. No missing-key defaults are applied.
    Groups are comma-separated exact labels with no surrounding whitespace;
    empty string is zero groups. Duplicates/empty segments refuse, never dedupe.
    Unknown keys stay private and are omitted, including credential fields.
    """
    try:
        _require(type(sources) is dict)
        sources = sources.copy()
        _require(sources.keys() == FILES)
        _require(all(type(value) is bytes and 0 < len(value) <= FILE_LIMIT
                     for value in sources.values()))
        _require(sum(map(len, sources.values())) <= TOTAL_LIMIT)
        # Snapshot references before parsing; immutable bytes cannot change.
        raw = {name:sources[name] for name in sorted(FILES)}
        parsed = {name:tomllib.loads(value.decode('utf-8')) for name,value in raw.items()}
        freq, hosts, vlans = (parsed[name] for name in ('freq.toml','hosts.toml','vlans.toml'))
        pve = freq['pve']; infrastructure = freq['infrastructure']
        _require(type(pve) is dict and type(infrastructure) is dict)
        host_rows = hosts['host']; vlan_rows = vlans['vlan']
        _require(type(host_rows) is list and len(host_rows) <= 4096)
        _require(type(vlan_rows) is dict and len(vlan_rows) <= 4096)
        nodes = pve['nodes']
        _require(type(nodes) is list and len(nodes) <= 4096)
        projected_hosts = []
        for row in host_rows:
            _require(type(row) is dict)
            projected_hosts.append(dict(address=row['ip'],label=row['label'],
                type=row['type'],groups=_groups(row['groups'])))
        projected_vlans = []
        for row in vlan_rows.values():
            _require(type(row) is dict)
            projected_vlans.append(dict(id=row['id'],name=row['name'],subnet=row['subnet']))
        payload = dict(hosts=projected_hosts,vlans=projected_vlans,
                       pve_nodes=list(nodes),cluster_name=infrastructure['cluster_name'])
        # The accepted codec remains byte-identical; its payload validator grants
        # neither identity nor permission. No dummy identity/artifact is invented.
        codec._payload(payload)
        payload['hosts'].sort(key=lambda row:row['address'])
        payload['vlans'].sort(key=lambda row:row['id'])
        payload['pve_nodes'].sort()
        _require(len(codec._canonical(payload)) <= codec.MAX_BYTES)
        return payload
    except Exception:
        raise ProjectionRefused(REFUSAL) from None
