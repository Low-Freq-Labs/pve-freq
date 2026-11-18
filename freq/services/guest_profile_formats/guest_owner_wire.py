"""Pure schema-two guest success DATA serialization, without admission.

The original owner must supply an already validated internal snapshot, retain
its own family/session/source/request duties and admit the SAME response after
serialization. A supplied owner_ref is only shape-checked DATA here. This code
neither issues a reference nor acquires, sends or acknowledges anything.
"""
import json

from .guest_wire import Projection, require


def project_guest_owner_wire(value):
    """Return bounded canonical UTF-8 sources, inventory or profile bytes.

    Preserve the exact accepted schema-one validators without accepting a
    schema-one response at this interface. The new owner_ref value and key are
    included in the same complete decoded-string and encoded-byte budgets.
    Open, retired and unavailable frames remain separate fixed formatters.
    All returned bytes remain unretained DATA, not an original response grant.
    """
    require(type(value) is dict and len(value) <= 8)
    require(all(type(key) is str for key in value))
    require(type(value.get('schema')) is int and value['schema'] == 2)
    kind = value.get('kind')
    require(type(kind) is str and kind in (
        'guest-sources', 'guest-inventory', 'guest-profile'))
    require('owner_ref' in value)
    projection = Projection()
    family = projection.reference(value['owner_ref'])
    # Only builtin keys/containers are inspected. The unchanged validator
    # constructs a fresh deep projection and rejects all extra/missing fields.
    base = {key: child for key, child in value.items() if key != 'owner_ref'}
    base['schema'] = 1
    snapshot = projection.document(base)
    snapshot['schema'] = 2
    snapshot['owner_ref'] = family

    def charge_keys(node):
        if type(node) is dict:
            for key, child in node.items():
                projection.text(key, 64)
                charge_keys(child)
        elif type(node) is list:
            for child in node:
                charge_keys(child)

    charge_keys(snapshot)
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                               sort_keys=True, separators=(',', ':'))
    output = bytearray()
    for chunk in encoder.iterencode(snapshot):
        data = chunk.encode('utf-8', 'strict')
        require(len(output) + len(data) <= 131072)
        output.extend(data)
    return bytes(output)
