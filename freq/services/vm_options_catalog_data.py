"""Private configured recipe catalog from retained bytes, never observation.

The eventual original owner owes fixed-name acquisition, exact presence/absence,
source/code/principal/writer cohort and physical lifetime. This parser accepts
bytes only; None or a caller's empty value cannot certify native absence. The
template section describes configured recipes, never observed VM identities.
"""
from dataclasses import dataclass
import json
import tomllib

from freq.services.vm_options_formats.bounded_json import CapacityExceeded, Refused
from freq.services.vm_options_formats.options_fields import grammar
from freq.services.vm_options_formats.wire_schema import SCHEMA


class OptionsCatalogUnavailable(ValueError):
    def __init__(self):
        super().__init__('VM options catalog unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class OptionsCatalogData:
    """Private immutable catalog piece; no complete configuration or authority."""
    rows: tuple
    catalog_bytes: bytes


def project_options_catalog_data(retained_distro_bytes):
    """Parse all declarations in fixed section order, refusing any invalid row.

No legacy name/tier defaults, coercion, filtering, truncation, loader, provider
or path access. Names may be empty only as allowed by unchanged schema. Unknown
recipe fields are not copied. Parser memory/time/traceback retention still need
the original supervised worker/end/resource profile; len checks prove none.
"""
    if type(retained_distro_bytes) is not bytes:
        raise OptionsCatalogUnavailable()
    if len(retained_distro_bytes) > 1048576:
        raise CapacityExceeded('VM options unavailable')
    failed = False
    try:
        document = tomllib.loads(retained_distro_bytes.decode('utf-8', 'strict'))
        output, immutable, keys = [], [], set()
        for section in ('distro', 'template'):
            entries = document.get(section, {})
            if type(entries) is not dict:
                raise OptionsCatalogUnavailable()
            # Combined ceiling, including rows that might otherwise be invalid.
            if len(entries) + len(output) > 64:
                raise CapacityExceeded('VM options unavailable')
            for key, info in entries.items():
                if key in keys or type(info) is not dict:
                    raise OptionsCatalogUnavailable()
                row = dict(key=key, name=info['name'], family=info['family'], tier=info['tier'])
                grammar(row, SCHEMA['$defs']['distro'])
                keys.add(key)
                output.append(row)
                immutable.append((key, row['name'], row['family'], row['tier']))
        grammar(output, SCHEMA['properties']['distros'])
        encoded = json.dumps(output, sort_keys=True, ensure_ascii=True,
                             allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > 1048576:
            raise CapacityExceeded('VM options unavailable')
    except CapacityExceeded:
        raise
    except (Refused, ValueError, KeyError, RecursionError):
        failed = True
    if failed:
        # No ordinary parser exception context or diagnostic source text.
        raise OptionsCatalogUnavailable()
    return OptionsCatalogData(tuple(immutable), encoded)


# No file read, native absence certificate, observed template/resource identity,
# original cohort attachment, bootstrap, full configuration/hash, wire or route.
