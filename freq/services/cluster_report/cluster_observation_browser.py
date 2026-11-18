"""Prepare private observed-browser JSON from fixed native response bytes.

This is a pure formatter, never a publisher or authority issuer. Source and
provenance literals are format claims only. The actual original owner must
retain its native verified TLS acquisition, source/cohort, credential, parser
result, request/session, cleanup and final once-response duty before disclosure.
Neither supplied input nor returned bytes can satisfy any of those obligations.
The preserved supplied-only browser schema and service are unchanged.
"""
import json

from .cluster_observation_structure import ParsedClusterRows, decode_native_response


PUBLIC_BODY_LIMIT = 2097152


def prepare_private_observation(native_body, observation_ref):
    """Return provisional canonical UTF-8 bytes or None, without any effects.

    No callback/parser, source flag, clock, provenance override or authority
    object is supplied. The correlation reference is validated data, never a
    transferable grant. The caller's original deadline is never renewed here.
    Only original final admission may make these private bytes public.
    """
    if (type(observation_ref) is not str or len(observation_ref) != 32 or
            any(c not in '0123456789abcdef' for c in observation_ref)):
        return None
    parsed = decode_native_response(native_body)
    if type(parsed) is not ParsedClusterRows:
        return None
    # This SAME fixed parser just created the private canonical body. No
    # caller-created ParsedClusterRows is accepted as an acquisition/format
    # shortcut; duplicate/unknown/unsupported native input already refused.
    structure = json.loads(parsed.body)
    document = {
        'schema': 'cluster-status-observation-browser-v1',
        'profile': 'pve-cluster-status-observation-v1',
        'observation_ref': observation_ref,
        'source': 'configured_pve_https',
        'state': ('reported_empty' if structure['cluster'] is None and
                  not structure['nodes'] else 'reported_rows'),
        'cluster': structure['cluster'],
        'nodes': structure['nodes'],
        'reported_count_relation': structure['reported_count_relation'],
        'provenance': {'transport': 'verified_tls',
                       'scope': 'credential_visible_response',
                       'completeness': 'unknown'},
        'authority': {'membership': 'provider_reported',
                      'node_status': 'provider_reported',
                      'health': 'unavailable', 'quorum': 'reported_only',
                      'identity': 'not_established', 'mutation': 'none'},
    }
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(',', ':')).encode('utf-8')
    return raw if len(raw) <= PUBLIC_BODY_LIMIT else None


# No original source/credential/TLS acquisition, registration, session,
# factory, live route, admission, response write or installation is added.
