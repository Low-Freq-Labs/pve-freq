"""Configured Fleet target projection from retained hosts bytes, DATA only.

The eventual original source owner must acquire and retain the fixed hosts file
with its original source/code/principal/writer lifetime. This function does not
establish that ownership, currentness, raw-file readability, an authenticated
response, SSH settings or execution permission. It is not joined to a route.
No legacy configuration loader, defaults, migration, file access or probes run.
"""
from dataclasses import dataclass
import hashlib
import json
import tomllib


HOSTS_BYTE_LIMIT = 2 * 1024 * 1024
TARGET_LIMIT = 1000
IDENTITY_BYTE_LIMIT = 256


class FleetTargetDataUnavailable(ValueError):
    def __init__(self):
        super().__init__('Configured Fleet target data unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class ConfiguredFleetTargetsData:
    """Ordered immutable pairs and correlation digest; never a source grant."""

    pairs: tuple
    target_set_sha256: str


def _identity(value):
    if type(value) is not str:
        raise FleetTargetDataUnavailable()
    if (not value or value != value.strip() or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise FleetTargetDataUnavailable()
    if len(value.encode('utf-8', errors='strict')) > IDENTITY_BYTE_LIMIT:
        raise FleetTargetDataUnavailable()
    return value


def decode_fleet_target_bytes(hosts_bytes):
    """Project explicit [[host]] rows, preserving all configured pair order.

    Explicit ``host=[]`` is a valid empty projection. A missing host collection,
    empty/missing file, malformed document, incomplete row or ambiguous alias
    refuses the entire projection. No valid prefix, skipped row, deduplication,
    inferred host name, expansion of groups/all_ips or fallback is returned.

    Other TOML metadata is parsed but neither returned nor validated as an SSH
    configuration. Therefore success is only this target projection's format
    result. The two MiB byte cap and count limits are logical DATA bounds, not
    CPU/heap/whole-job limits. Fixed parsing must run outside admission gates
    under the genuine original parent's qualified supervision and inherited end.
    """
    if type(hosts_bytes) is not bytes or not 0 < len(hosts_bytes) <= HOSTS_BYTE_LIMIT:
        raise FleetTargetDataUnavailable()
    refused = False
    try:
        document = tomllib.loads(hosts_bytes.decode('utf-8', errors='strict'))
    except (UnicodeError, tomllib.TOMLDecodeError):
        refused = True
    if refused:
        # Do not retain parser diagnostic/context or the supplied document in
        # an outward exception. Unexpected allocation/control errors propagate.
        raise FleetTargetDataUnavailable()
    rows = document.get('host')
    if type(rows) is not list or len(rows) > TARGET_LIMIT:
        raise FleetTargetDataUnavailable()
    pairs, aliases = [], {}
    for index, row in enumerate(rows):
        if type(row) is not dict or 'label' not in row or 'ip' not in row:
            raise FleetTargetDataUnavailable()
        label, address = _identity(row['label']), _identity(row['ip'])
        for alias in (label, address):
            if alias in aliases and aliases[alias] != index:
                raise FleetTargetDataUnavailable()
            aliases[alias] = index
        pairs.append((label, address))
    ordered = tuple(pairs)
    canonical = json.dumps(sorted(ordered), ensure_ascii=True,
                           separators=(',', ':')).encode('ascii')
    digest = hashlib.sha256(canonical).hexdigest()
    return ConfiguredFleetTargetsData(ordered, digest)


# No original owner constructor, request binding, wire response, route, native
# acquisition/currentness, credential/transport selection or installed behavior.
