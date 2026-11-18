"""Private fixed profile section request DATA, no resolver or native grant.

Caller must preown its actual original registered section duty, whole-job
request/credential/trust/native/parser/wire allowances and current source and
recipient. Copied transport scalars and plan never prove those rights. No
socket/TLS/clock/logging/cache/credential lookup exists in this formatter.
"""
from freq.services.node_read_profile import WireTarget, _ascii, _endpoint, _tls_name
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData


REQUEST_LIMIT = 4096
_SUFFIXES = (
    ('status', '/status/current'),
    ('configured_network', '/config'),
    ('guest_network', '/agent/network-get-interfaces'),
)


def serialize_profile_section_request(plan, section, transport, credentials):
    """Only one of the canonical three GETs; returns private bytes only.

    Plan target selects the fixed guest path. WireTarget.node does not become
    that path: its copied transport source identity is a different duty. No
    supplied path/URL/query/header/method/callback is accepted. The original
    caller still authenticates SAME configured source/token/TLS/guest result;
    this serializer only validates safe bounded scalar DATA.
    """
    if (type(plan) is not _GuestProfileSubreadsData or
            type(section) is not str or section not in tuple(row[0] for row in _SUFFIXES) or
            type(plan.target) is not tuple or len(plan.target) != 3):
        raise ValueError('Guest profile request unavailable')
    node, kind, vmid = plan.target
    _ascii(node, 1, 64, r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}')
    if (type(kind) is not str or kind != 'qemu' or
            type(vmid) is not int or not 100 <= vmid <= 999999999 or
            type(plan.reads) is not tuple or len(plan.reads) != 3 or
            type(plan.unsupported_sections) is not tuple or plan.unsupported_sections != ()):
        raise ValueError('Guest profile request unavailable')
    prefix = '/api2/json/nodes/' + node + '/qemu/' + str(vmid)
    path = None
    for index, (name, suffix) in enumerate(_SUFFIXES):
        row = plan.reads[index]
        # Strict builtin row types keep custom equality out of fixed DATA.
        if (type(row) is not tuple or len(row) != 4 or
                any(type(value) is not str for value in row[:3]) or
                type(row[3]) is not int or row != (name, 'GET', prefix + suffix, 262144)):
            raise ValueError('Guest profile request unavailable')
        if name == section:
            path = row[2]
    if path is None or type(transport) is not WireTarget:
        raise ValueError('Guest profile request unavailable')
    endpoint, version = _endpoint(transport.endpoint)
    _tls_name(transport.tls_name)
    _ascii(transport.node, 1, 128, r'[A-Za-z0-9_-]+')
    if type(credentials) is not tuple or len(credentials) != 3:
        raise ValueError('Guest profile request unavailable')
    principal, token_id, secret = credentials
    _ascii(principal, 3, 257, r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+')
    user, realm = principal.split('@')
    _ascii(user, 1, 128, r'[A-Za-z0-9_.-]+')
    _ascii(realm, 1, 128, r'[A-Za-z0-9_.-]+')
    _ascii(token_id, 1, 128, r'[A-Za-z0-9_.-]+')
    _ascii(secret, 1, 512, r'[A-Za-z0-9._~-]+')
    host = ('[' + endpoint + ']' if version == 6 else endpoint) + ':8006'
    request = (
        'GET ' + path + ' HTTP/1.1\r\n'
        'Host: ' + host + '\r\n'
        'Authorization: PVEAPIToken=' + principal + '!' + token_id + '=' + secret + '\r\n'
        'Accept: application/json\r\n'
        'Connection: close\r\n\r\n'
    ).encode('ascii')
    if len(request) > REQUEST_LIMIT:
        raise ValueError('Guest profile request unavailable')
    return request


# Returned bytes and exceptions can retain private material. No erasure or
# retained-heap/RSS/process allowance claim; no request is sent by this module.
