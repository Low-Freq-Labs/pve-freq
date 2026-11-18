"""Pure configuration-metadata artifact codec; no authority or filesystem effects.

Callers must supply admitted source identity and a complete typed projection.
Validation does not grant export/download/apply permission or prove recovery.
"""

import hashlib
import ipaddress
import json
import re

FORMAT = "freq-configuration-export-v1"
SCOPE = "configuration_metadata_v1"
MAX_BYTES = 8 * 1024 * 1024
EXCLUDED = [
    "accounts",
    "vault",
    "credentials",
    "key_paths",
    "guest_volumes",
    "application_databases",
    "sessions",
    "license_material",
    "runtime_observations",
]


class ArtifactRefused(ValueError):
    """Static refusal; caller data must never appear in an error."""


def _require(condition):
    if not condition:
        raise ArtifactRefused("Configuration artifact validation failed")


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names.split()))


def _text(value, limit=256, empty=False):
    _require(type(value) is str and len(value) <= limit and (empty or bool(value)))
    _require(all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value))
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ArtifactRefused("Configuration artifact validation failed") from None


def _opaque(value):
    _require(type(value) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", value))


def _identity(value):
    _keys(value, "installation_id installation_incarnation estate_id configuration_revision")
    for item in value.values():
        _opaque(item)


def _id(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value))


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ArtifactRefused("Configuration artifact validation failed") from None


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _address(value):
    _text(value, 45)
    _require("%" not in value)
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        raise ArtifactRefused("Configuration artifact validation failed") from None
    _require(str(parsed) == value)


def _payload(value):
    _keys(value, "hosts vlans pve_nodes cluster_name")
    for name in ("hosts", "vlans", "pve_nodes"):
        _require(type(value[name]) is list and len(value[name]) <= 4096)
    _text(value["cluster_name"], empty=True)
    addresses = set()
    for host in value["hosts"]:
        _keys(host, "address label type groups")
        _address(host["address"])
        _require(host["address"] not in addresses)
        addresses.add(host["address"])
        _text(host["label"])
        _text(host["type"], 64)
        _require(type(host["groups"]) is list and len(host["groups"]) <= 128)
        for group in host["groups"]:
            _text(group, 128)
        _require(len(set(host["groups"])) == len(host["groups"]))
    vlans = set()
    for vlan in value["vlans"]:
        _keys(vlan, "id name subnet")
        _require(type(vlan["id"]) is int and 1 <= vlan["id"] <= 4094 and vlan["id"] not in vlans)
        vlans.add(vlan["id"])
        _text(vlan["name"])
        _text(vlan["subnet"], 49)
        _require("%" not in vlan["subnet"])
        try:
            network = ipaddress.ip_network(vlan["subnet"], strict=True)
        except ValueError:
            raise ArtifactRefused("Configuration artifact validation failed") from None
        _require(str(network) == vlan["subnet"])
    for node in value["pve_nodes"]:
        _address(node)
    _require(len(set(value["pve_nodes"])) == len(value["pve_nodes"]))


def _validate(value):
    _keys(value, "format artifact_id product source scope created_at expires_at excluded payload payload_sha256")
    _require(value["format"] == FORMAT and value["scope"] == SCOPE)
    _id(value["artifact_id"])
    _keys(value["product"], "name version")
    _require(value["product"]["name"] == "pve-freq")
    _opaque(value["product"]["version"])
    _identity(value["source"])
    created, expires = value["created_at"], value["expires_at"]
    _require(type(created) is int and type(expires) is int and 0 < created < expires <= 253402300799)
    _require(expires - created <= 86400)
    _require(value["excluded"] == EXCLUDED)
    _payload(value["payload"])
    _require(value["payload_sha256"] == _digest(_canonical(value["payload"])))


def encode_artifact(*, artifact_id, source, version, created_at, expires_at, payload):
    """Encode an explicitly supplied projection; does not collect or save config."""
    value = dict(
        format=FORMAT,
        artifact_id=artifact_id,
        source=source,
        product=dict(name="pve-freq", version=version),
        scope=SCOPE,
        created_at=created_at,
        expires_at=expires_at,
        excluded=EXCLUDED,
        payload=payload,
        payload_sha256=_digest(_canonical(payload)),
    )
    _validate(value)
    encoded = _canonical(value)
    _require(len(encoded) <= MAX_BYTES)
    return encoded


def decode_artifact(encoded, expected_sha256):
    """Validate exact bytes against an independently trusted digest, without IO."""
    _require(type(encoded) is bytes and 0 < len(encoded) <= MAX_BYTES)
    _require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256))
    _require(_digest(encoded) == expected_sha256)

    def members(pairs):
        out = {}
        for key, item in pairs:
            _require(key not in out)
            out[key] = item
        return out

    def nonfinite(_):
        raise ArtifactRefused("Configuration artifact validation failed")

    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=members, parse_constant=nonfinite)
        _validate(value)
        _require(_canonical(value) == encoded)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ArtifactRefused("Configuration artifact validation failed") from None
    return value


def compatibility_preview(encoded, expected_sha256, *, target, version, now):
    """Syntax/identity preview only; no current conflict/readiness or apply claim."""
    value = decode_artifact(encoded, expected_sha256)
    _identity(target)
    _opaque(version)
    _require(type(now) is int and 0 < now <= 253402300799)
    _require(value["created_at"] <= now and value["product"]["version"] == version)
    _require(
        all(value["source"][key] == target[key] for key in ("installation_id", "installation_incarnation", "estate_id"))
    )
    return dict(
        schema="configuration-compatibility-v1",
        artifact_id=value["artifact_id"],
        artifact_sha256=expected_sha256,
        bytes=len(encoded),
        source=value["source"],
        target=dict(target),
        scope=SCOPE,
        excluded=list(EXCLUDED),
        product=value["product"],
        state="artifact_compatible_only",
        download_expired=now >= value["expires_at"],
        target_conflicts="not_checked",
        recovery_verified=False,
        apply_authorized=False,
    )
