"""Join private transport bytes to the unchanged supplied node parser.

Neither an HTTPS response nor this structural parser grants authenticity,
coverage, current-state or disclosure authority. No scope is synthesized here.
"""
from .node_observation import envelope, network_list
from .node_read_registry import TargetRecord, TargetSpec
from .node_read_profile import WireTarget


def decode_provisional(record, original_scope, raw):
    """Return the original envelope slice or None, never a public result."""
    if type(record) is not TargetRecord or type(record.spec) is not TargetSpec:
        return None
    if type(record.spec.wire) is not WireTarget:
        return None
    if type(original_scope) is not network_list.NodeScope:
        return None
    if (record.spec.parser_profile != "supplied-node-network-list-v1"
            or original_scope.profile_ref != record.spec.parser_profile
            or original_scope.node_name != record.spec.wire.node
            or original_scope.query_filter is not None):
        return None
    result = envelope.decode_envelope(original_scope, raw)
    if type(result) is not envelope.EnvelopeSlice or result.envelope is not raw:
        return None
    return result
