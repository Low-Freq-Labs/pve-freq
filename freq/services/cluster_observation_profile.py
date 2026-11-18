"""Fixed Cluster wire bytes only; no credential lookup, issuer or admission.

Original startup/cohort owners retain the actual per-node token and verified
TLS context. WireTarget is reused solely as copied validated transport scalars;
its node is checked but never becomes a request path or provider identity proof.
Nothing here selects this transport from an HTTP route or enables a service.
"""
from .node_read_profile import WireTarget, _ascii, _endpoint, _tls_name


REQUEST_LIMIT = 4096


def serialize_request(target, credentials):
    """Serialize the single fixed GET before acquiring a native socket.

    The original caller reserves payload capacity before resolving its private
    token. This function neither resolves nor stores credentials. Exceptions,
    frames and caller-held values may retain them; erasure is not claimed.
    """
    if type(target) is not WireTarget:
        raise ValueError("cluster read profile unavailable")
    endpoint, version = _endpoint(target.endpoint)
    _tls_name(target.tls_name)
    _ascii(target.node, 1, 128, r"[A-Za-z0-9_-]+")
    if type(credentials) is not tuple or len(credentials) != 3:
        raise ValueError("cluster read profile unavailable")
    user_realm, token_id, secret = credentials
    _ascii(user_realm, 3, 257, r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+")
    user, realm = user_realm.split("@")
    _ascii(user, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(realm, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(token_id, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(secret, 1, 512, r"[A-Za-z0-9._~-]+")
    host = ("[" + endpoint + "]" if version == 6 else endpoint) + ":8006"
    request = (
        "GET /api2/json/cluster/status HTTP/1.1\r\n"
        "Host: " + host + "\r\n"
        "Authorization: PVEAPIToken=" + user_realm + "!" + token_id + "=" + secret + "\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    if len(request) > REQUEST_LIMIT:
        raise ValueError("cluster read profile unavailable")
    return request
